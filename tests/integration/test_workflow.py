"""Opt-in tests against real Compose processes, PostgreSQL and Redis/Celery.

These do not start/stop infrastructure or substitute mocked dependencies.
"""

import json
import os
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from dotenv import dotenv_values

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def compose(*args: str) -> str:
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def wait_ready(client: httpx.Client, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if client.get("/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        assert time.monotonic() < deadline, "gateway did not become ready"
        time.sleep(0.5)


def wait_terminal(client: httpx.Client, identifier: str, timeout: float = 45) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/v1/jobs/{identifier}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            return cast(dict[str, Any], job)
        assert time.monotonic() < deadline, f"job did not finish: {job['status']}"
        time.sleep(0.5)


@pytest.fixture
def live_gateway() -> Iterator[httpx.Client]:
    if os.getenv("INCIDENTPILOT_RUN_INTEGRATION") != "1":
        pytest.skip("requires a running Compose sandbox; set INCIDENTPILOT_RUN_INTEGRATION=1")
    values = dotenv_values(ROOT / ".env")
    token = os.getenv("INCIDENTPILOT_SANDBOX_AUTH_TOKEN") or values.get(
        "INCIDENTPILOT_SANDBOX_AUTH_TOKEN"
    )
    if not token:
        pytest.fail("integration enabled but sandbox auth token is missing")
    gateway_port = os.getenv("INCIDENTPILOT_GATEWAY_PORT") or values.get(
        "INCIDENTPILOT_GATEWAY_PORT", "8000"
    )
    with httpx.Client(
        base_url=f"http://127.0.0.1:{gateway_port}",
        timeout=10,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        # When explicitly enabled, missing services fail instead of silently skipping.
        client.get("/ready").raise_for_status()
        yield client


def test_real_job_execution_persistence_and_correlation(live_gateway: httpx.Client) -> None:
    correlation = str(uuid4())
    response = live_gateway.post(
        "/v1/jobs",
        json={"description": "hello incident pilot"},
        headers={"X-Request-ID": correlation, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202
    assert response.headers["X-Request-ID"] == correlation
    assert response.json()["status"] == "queued"
    identifier = UUID(response.json()["id"])
    job = wait_terminal(live_gateway, str(identifier))
    assert job["status"] == "completed"
    assert job["result"]["word_count"] == 3
    # UUID validation above makes this fixed SQL safe; no user-provided SQL path exists.
    row = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "incidentpilot",
        "-Atc",
        f"SELECT status || ':' || (result->>'word_count') FROM jobs WHERE id = '{identifier}'",
    )
    assert row.strip() == "completed:3"
    for service in ["gateway", "auth", "data", "worker"]:
        logs = compose("logs", "--no-color", "--since", "2m", service)
        assert correlation in logs, f"missing originating request ID in {service} logs"


def test_idempotency_is_concurrent_durable_and_owner_scoped(live_gateway: httpx.Client) -> None:
    key = f"concurrent-{uuid4()}"

    def submit() -> httpx.Response:
        return live_gateway.post(
            "/v1/jobs",
            json={"description": "one durable job"},
            headers={"Idempotency-Key": key},
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: submit(), range(6)))
    assert {response.status_code for response in responses} == {202}
    assert len({response.json()["id"] for response in responses}) == 1
    replayed = [response.headers["Idempotency-Replayed"] for response in responses]
    assert replayed.count("false") == 1
    assert replayed.count("true") == 5
    conflict = live_gateway.post(
        "/v1/jobs",
        json={"description": "conflicting payload"},
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409

    compose("restart", "data")
    wait_ready(live_gateway)
    replay = submit()
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == responses[0].json()["id"]

    script = f"""
import os
import httpx
headers = {{'X-Internal-Token': os.environ['INCIDENTPILOT_INTERNAL_TOKEN']}}
base = 'http://data:8000/v1/jobs'
payload = {{'description': 'owner scope', 'idempotency_key': '{key}', 'payload_sha256': '0' * 64}}
with httpx.Client(timeout=5, headers=headers) as client:
    first = client.post(base, json={{**payload, 'owner_id': 'owner-a'}})
    second = client.post(base, json={{**payload, 'owner_id': 'owner-b'}})
    assert first.status_code == second.status_code == 201
    assert first.json()['job']['id'] != second.json()['job']['id']
"""
    compose("exec", "-T", "data", "python", "-c", script)


def test_worker_and_gateway_restart_and_duplicate_delivery(live_gateway: httpx.Client) -> None:
    key = f"restart-{uuid4()}"
    compose("stop", "worker")
    try:
        submitted = live_gateway.post(
            "/v1/jobs",
            json={"description": "survives worker restart"},
            headers={"Idempotency-Key": key},
        )
        assert submitted.status_code == 202
        identifier = submitted.json()["id"]
        assert live_gateway.get(f"/v1/jobs/{identifier}").json()["status"] == "queued"
    finally:
        compose("start", "worker")
    assert wait_terminal(live_gateway, identifier)["status"] == "completed"

    publish = f"""
import os
from incidentpilot.services.worker.queue import TASK_NAME, create_queue
queue = create_queue(os.environ['INCIDENTPILOT_BROKER_URL'])
queue.send_task(TASK_NAME, args=['{identifier}', '{uuid4()}'], retry=False)
queue.send_task(TASK_NAME, args=['{identifier}', '{uuid4()}'], retry=False)
queue.close()
"""
    compose("exec", "-T", "gateway", "python", "-c", publish)
    time.sleep(3)
    assert live_gateway.get(f"/v1/jobs/{identifier}").json()["status"] == "completed"

    compose("restart", "gateway")
    wait_ready(live_gateway)
    replay = live_gateway.post(
        "/v1/jobs",
        json={"description": "survives worker restart"},
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == identifier


def test_redis_interruption_retains_truthful_failed_replay(live_gateway: httpx.Client) -> None:
    key = f"redis-down-{uuid4()}"
    compose("stop", "redis")
    try:
        failed = live_gateway.post(
            "/v1/jobs",
            json={"description": "broker unavailable"},
            headers={"Idempotency-Key": key},
        )
        assert failed.status_code == 503
        identifier = failed.json()["detail"]["job_id"]
        job = live_gateway.get(f"/v1/jobs/{identifier}")
        assert job.status_code == 200
        assert job.json()["status"] == "failed"
        assert job.json()["error"] == "enqueue_failed"
    finally:
        compose("start", "redis")
    wait_ready(live_gateway)
    replay = live_gateway.post(
        "/v1/jobs",
        json={"description": "broker unavailable"},
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == identifier
    assert replay.json()["status"] == "failed"


def test_real_postgresql_crud_via_data_http(live_gateway: httpx.Client) -> None:
    # Execute a fixed HTTP check inside the private network; the data API has no host port.
    key = f"crud-{uuid4()}"
    script = f"""
import os
import httpx
with httpx.Client(base_url='http://data:8000', timeout=5,
                  headers={{'X-Internal-Token': os.environ['INCIDENTPILOT_INTERNAL_TOKEN']}}) as c:
    created = c.post('/v1/jobs', json={{'owner_id': 'integration-only', 'description': 'crud check',
                                      'idempotency_key': '{key}', 'payload_sha256': '0' * 64}})
    assert created.status_code == 201, created.status_code
    identifier = created.json()['job']['id']
    path = '/v1/jobs/' + identifier
    assert c.get(path).json()['status'] == 'queued'
    assert c.patch(path, json={{'status': 'completed'}}).status_code == 422
    assert c.patch(path, json={{'status': 'running'}}).status_code == 200
    failed = c.patch(path, json={{'status': 'failed', 'error': 'integration check'}})
    assert failed.status_code == 200
    assert c.patch(path, json={{'status': 'running'}}).status_code == 409
    assert c.get(path).json()['status'] == 'failed'
    print(identifier)
"""
    identifier = UUID(compose("exec", "-T", "data", "python", "-c", script).strip())
    # The gateway enforces ownership even for internally created jobs.
    assert live_gateway.get(f"/v1/jobs/{identifier}").status_code == 404
    row = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "incidentpilot",
        "-Atc",
        f"SELECT row_to_json(jobs) FROM jobs WHERE id = '{identifier}'",
    )
    persisted = json.loads(row)
    assert persisted["status"] == "failed"
    assert persisted["error"] == "integration check"


def test_read_only_evidence_plane_reads_real_sources(live_gateway: httpx.Client) -> None:
    values = dotenv_values(ROOT / ".env")
    port = os.getenv("INCIDENTPILOT_CONTROL_PLANE_PORT") or values.get(
        "INCIDENTPILOT_CONTROL_PLANE_PORT", "8001"
    )
    correlation = str(uuid4())
    submitted = live_gateway.post(
        "/v1/jobs",
        json={"description": "evidence integration check"},
        headers={"X-Request-ID": correlation, "Idempotency-Key": str(uuid4())},
    )
    submitted.raise_for_status()
    identifier = submitted.json()["id"]
    job = wait_terminal(live_gateway, identifier)
    assert job["status"] == "completed"
    time.sleep(10)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as evidence:
        logs = evidence.get(
            "/v1/evidence/logs",
            params={"service": "gateway", "request_id": correlation, "limit": 20},
        )
        logs.raise_for_status()
        events = logs.json()["events"]
        assert any(event["request_id"] == correlation for event in events)
        trace_id = next(event["trace_id"] for event in events if event["trace_id"])
        trace = evidence.get(f"/v1/evidence/traces/{trace_id}")
        trace.raise_for_status()
        assert {"gateway", "auth", "data", "worker"} <= set(trace.json()["services"])
        metrics = evidence.get("/v1/evidence/metrics/jobs", params={"window_seconds": 900})
        metrics.raise_for_status()
        assert metrics.json()["provenance"]["result_count"] > 0
        services = evidence.get("/v1/evidence/services")
        services.raise_for_status()
        assert all(item["alive"] for item in services.json()["services"])
        deployments = evidence.get("/v1/evidence/deployments")
        deployments.raise_for_status()
        assert deployments.json()["deployments"][0]["git_sha"] == (
            "afca0b9eb853d346a86c0edc14d13b4a82e49ba9"
        )
