from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from incidentpilot.shared.config import AuthSettings, DataSettings, GatewaySettings, WorkerSettings
from incidentpilot.shared.request_id import normalize_request_id
from incidentpilot.shared.schemas import (
    JobInput,
    JobPatch,
    JobResult,
    JobStatus,
    transition_allowed,
)


@pytest.mark.parametrize("value", [None, "", "not-an-id", "a" * 200, "\r\nbad"])
def test_request_id_generates_valid_uuid(value: str | None) -> None:
    assert str(UUID(normalize_request_id(value)))


def test_request_id_preserved() -> None:
    identifier = "c78fa62a-0c19-485b-aa21-0a6a6c7a8f30"
    assert normalize_request_id(identifier.upper()) == identifier


@pytest.mark.parametrize("description", ["", "   ", "x" * 1001])
def test_invalid_job_input(description: str) -> None:
    with pytest.raises(ValidationError):
        JobInput(description=description)


@pytest.mark.parametrize("status", list(JobStatus))
def test_terminal_states_cannot_transition(status: JobStatus) -> None:
    assert not transition_allowed(JobStatus.COMPLETED, status)
    assert not transition_allowed(JobStatus.FAILED, status)


def test_lifecycle_and_outcomes() -> None:
    assert transition_allowed(JobStatus.QUEUED, JobStatus.RUNNING)
    assert transition_allowed(JobStatus.QUEUED, JobStatus.FAILED)
    assert transition_allowed(JobStatus.RUNNING, JobStatus.COMPLETED)
    assert not transition_allowed(JobStatus.QUEUED, JobStatus.COMPLETED)
    assert not transition_allowed(JobStatus.RUNNING, JobStatus.QUEUED)
    result = JobResult(word_count=1, character_count=1, sha256="a" * 64)
    assert JobPatch(status=JobStatus.COMPLETED, result=result).result == result
    assert JobPatch(status=JobStatus.FAILED, error="failed").error == "failed"
    for body in [
        {"status": "completed"},
        {"status": "failed"},
        {"status": "running", "error": "bad"},
        {"status": "completed", "result": result, "error": "bad"},
        {"status": "failed", "result": result, "error": "bad"},
    ]:
        with pytest.raises(ValidationError):
            JobPatch.model_validate(body)


def test_required_configuration_and_secret_repr() -> None:
    for model in [AuthSettings, DataSettings, GatewaySettings, WorkerSettings]:
        with pytest.raises(ValidationError):
            model()
    token = SecretStr("unit-test-only-token")
    assert token.get_secret_value() not in repr(AuthSettings(sandbox_auth_token=token))
    with pytest.raises(ValidationError):
        AuthSettings(sandbox_auth_token=SecretStr("short"))


@pytest.mark.parametrize("url", ["sqlite:///jobs.db", "postgresql+psycopg://", "http://db"])
def test_reject_invalid_database_configuration(url: str) -> None:
    with pytest.raises(ValidationError):
        DataSettings(database_url=SecretStr(url), internal_token=SecretStr("unit-test-only-token"))


def test_service_configuration_validation() -> None:
    values = {
        "auth_url": "http://auth:8000/",
        "data_url": "http://data:8000/",
        "broker_url": "redis://redis:6379/0",
        "internal_token": "unit-test-only-token",
    }
    assert GatewaySettings.model_validate(values).data_url == "http://data:8000"
    for key, value in [
        ("auth_url", "file:///tmp"),
        ("data_url", "http://user:pass@data"),
        ("data_url", "http://data?x=y"),
        ("broker_url", "memory://"),
        ("http_timeout", 0),
        ("http_timeout", 31),
    ]:
        with pytest.raises(ValidationError):
            GatewaySettings.model_validate({**values, key: value})
    worker = {key: value for key, value in values.items() if key != "auth_url"}
    for limit in [-1, 6]:
        with pytest.raises(ValidationError):
            WorkerSettings.model_validate({**worker, "worker_retry_limit": limit})
    assert WorkerSettings.model_validate(worker).worker_retry_limit == 3
    assert DataSettings(
        database_url=SecretStr("postgresql+psycopg://user:local@db/jobs"),
        internal_token=SecretStr("unit-test-only-token"),
    ).database_url
