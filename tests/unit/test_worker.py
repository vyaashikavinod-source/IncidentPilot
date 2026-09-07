import importlib
from datetime import UTC, datetime
from types import ModuleType
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from celery.exceptions import Retry

from incidentpilot.services.worker.processing import process_job, record_failure
from incidentpilot.shared.clients import DataClient, UpstreamError
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.schemas import Job, JobStatus


@pytest.mark.parametrize(
    "status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED]
)
def test_deterministic_processing_and_terminal_delivery(status: JobStatus) -> None:
    job = Job(
        id=uuid4(),
        owner_id="sandbox-user",
        description="hello world",
        status=status,
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    updates: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            updates.append(request.content)
        return httpx.Response(200, json=job.model_dump(mode="json"))

    client = DataClient("http://data", 1, "test", httpx.MockTransport(respond))
    process_job(client, job.id)
    if status in {JobStatus.COMPLETED, JobStatus.FAILED}:
        assert updates == []
    else:
        import json

        assert json.loads(updates[0])["status"] == "running"
        result = json.loads(updates[1])
        assert result["status"] == "completed"
        assert result["result"]["word_count"] == 2
        assert result["result"]["character_count"] == 11
    client.close()


def test_best_effort_failure_logging() -> None:
    client = DataClient(
        "http://data", 1, "test", httpx.MockTransport(lambda r: httpx.Response(503))
    )
    record_failure(client, uuid4())
    client.close()


def test_concurrent_duplicate_that_became_terminal_is_safe() -> None:
    job = Job(
        id=uuid4(),
        owner_id="sandbox-user",
        description="hello",
        status=JobStatus.QUEUED,
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "PATCH":
            return httpx.Response(409)
        state = JobStatus.COMPLETED if calls > 1 else JobStatus.QUEUED
        return httpx.Response(
            200, json=job.model_copy(update={"status": state}).model_dump(mode="json")
        )

    client = DataClient("http://data", 1, "test", httpx.MockTransport(respond))
    process_job(client, job.id)
    assert calls == 3
    client.close()


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("INCIDENTPILOT_DATA_URL", "http://data")
    monkeypatch.setenv("INCIDENTPILOT_INTERNAL_TOKEN", "unit-test-only-token")
    monkeypatch.setenv("INCIDENTPILOT_BROKER_URL", "redis://redis/0")
    return importlib.import_module("incidentpilot.services.worker.app")


@pytest.mark.parametrize("retries,status", [(0, 503), (3, 503), (0, 404)])
def test_bounded_task_retry(
    worker: ModuleType, monkeypatch: pytest.MonkeyPatch, retries: int, status: int
) -> None:
    client = Mock()
    monkeypatch.setattr(worker, "DataClient", Mock(return_value=client))
    error = UpstreamError("upstream_http_failure", status)
    monkeypatch.setattr(worker, "process_job", Mock(side_effect=error))
    failure = Mock()
    monkeypatch.setattr(worker, "record_failure", failure)
    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(worker.run_job, "retry", retry)
    worker.run_job.push_request(retries=retries)
    try:
        with pytest.raises(Retry if retries == 0 and status == 503 else UpstreamError):
            worker.run_job.run(str(uuid4()), str(uuid4()))
    finally:
        worker.run_job.pop_request()
    assert retry.call_count == (1 if retries == 0 and status == 503 else 0)
    assert failure.call_count == (0 if retry.called else 1)
    client.close.assert_called_once()
    assert request_id.get() == "-"


def test_worker_unexpected_error_records_failure(
    worker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "DataClient", Mock(return_value=Mock()))
    monkeypatch.setattr(worker, "process_job", Mock(side_effect=ValueError("operation error")))
    failure = Mock()
    monkeypatch.setattr(worker, "record_failure", failure)
    with pytest.raises(ValueError):
        worker.run_job.run(str(uuid4()), str(uuid4()))
    failure.assert_called_once()
