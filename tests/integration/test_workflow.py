"""Opt-in tests against real Compose processes, PostgreSQL and Redis/Celery.

These do not start/stop infrastructure or substitute mocked dependencies.
"""

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
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
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
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
        headers={"X-Request-ID": correlation},
    )
    assert response.status_code == 202
    assert response.headers["X-Request-ID"] == correlation
    assert response.json()["status"] == "queued"
    identifier = UUID(response.json()["id"])
    deadline = time.monotonic() + 45
    while True:
        current = live_gateway.get(f"/v1/jobs/{identifier}")
        current.raise_for_status()
        job = current.json()
        if job["status"] in {"completed", "failed"}:
            break
        assert time.monotonic() < deadline, f"job did not finish: {job['status']}"
        time.sleep(0.5)
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


def test_real_postgresql_crud_via_data_http(live_gateway: httpx.Client) -> None:
    # Execute a fixed HTTP check inside the private network; the data API has no host port.
    script = """
import os
import httpx
with httpx.Client(base_url='http://data:8000', timeout=5,
                  headers={'X-Internal-Token': os.environ['INCIDENTPILOT_INTERNAL_TOKEN']}) as c:
    created = c.post('/v1/jobs', json={'owner_id': 'integration-only', 'description': 'crud check'})
    assert created.status_code == 201, created.status_code
    identifier = created.json()['id']
    path = '/v1/jobs/' + identifier
    assert c.get(path).json()['status'] == 'queued'
    assert c.patch(path, json={'status': 'completed'}).status_code == 422
    assert c.patch(path, json={'status': 'running'}).status_code == 200
    assert c.patch(path, json={'status': 'failed', 'error': 'integration check'}).status_code == 200
    assert c.patch(path, json={'status': 'running'}).status_code == 409
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
