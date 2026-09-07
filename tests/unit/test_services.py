import io
import json
from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from incidentpilot.services.auth.app import create_app as auth_app
from incidentpilot.services.data.app import create_app as data_app
from incidentpilot.services.gateway.app import create_app as gateway_app
from incidentpilot.shared.clients import UpstreamError
from incidentpilot.shared.config import AuthSettings, DataSettings, GatewaySettings, Settings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.schemas import Job, JobStatus


@pytest.mark.parametrize("authorization", [None, "", "Basic wrong", "Bearer wrong", "Bearer é"])
def test_auth_rejects_invalid_credentials(authorization: str | None) -> None:
    app = auth_app(AuthSettings(sandbox_auth_token=SecretStr("unit-test-only-token")))
    with TestClient(app) as client:
        headers = {"Authorization": authorization} if authorization is not None else {}
        # HTTP header values must be ASCII; non-ASCII is tested via UTF-8 bytes.
        response = client.post(
            "/v1/auth/validate", headers={k: v.encode() for k, v in headers.items()}
        )
        assert response.status_code == 401


def test_auth_health_identity_and_correlation_logs() -> None:
    app = auth_app(AuthSettings(sandbox_auth_token=SecretStr("unit-test-only-token")))
    stream = io.StringIO()
    correlation = str(uuid4())
    with TestClient(app) as client:
        configure_logging(Settings(service_name="auth"), stream)
        assert client.get("/health").json() == {"status": "alive"}
        assert client.get("/ready").json() == {"status": "ready"}
        response = client.post(
            "/v1/auth/validate",
            headers={
                "Authorization": "Bearer unit-test-only-token",
                "X-Request-ID": correlation,
            },
        )
    assert response.json() == {
        "subject": "sandbox-user",
        "roles": ["sandbox_user"],
        "authenticated": True,
    }
    assert response.headers["X-Request-ID"] == correlation
    assert json.loads(stream.getvalue().splitlines()[-1])["request_id"] == correlation
    assert request_id.get() == "-"
    assert "unit-test-only-token" not in stream.getvalue()


def test_unexpected_http_error_is_correlated_and_safe() -> None:
    app = auth_app(AuthSettings(sandbox_auth_token=SecretStr("unit-test-only-token")))
    correlation = str(uuid4())

    @app.get("/unexpected")
    def unexpected() -> None:
        raise RuntimeError("private failure detail")

    with TestClient(app) as client:
        response = client.get("/unexpected", headers={"X-Request-ID": correlation})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == correlation
    assert response.json() == {"detail": "internal_server_error"}


@pytest.fixture
def gateway() -> TestClient:
    config = GatewaySettings(
        auth_url="http://auth",
        data_url="http://data",
        broker_url=SecretStr("redis://redis/0"),
        internal_token=SecretStr("unit-test-only-token"),
    )
    return TestClient(gateway_app(config))


def test_gateway_authenticated_submission_and_metadata(
    gateway: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = cast(FastAPI, gateway.app)
    correlation = str(uuid4())
    job = Job(
        id=uuid4(),
        owner_id="sandbox-user",
        description="hello world",
        status=JobStatus.QUEUED,
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Request-ID"] == correlation
        seen.append(request.url.host)
        if request.url.host == "auth":
            return httpx.Response(
                200,
                json={"subject": "sandbox-user", "roles": ["sandbox_user"], "authenticated": True},
            )
        return httpx.Response(200, json=job.model_dump(mode="json"))

    # Typed clients perform real serialization over isolated mock transports, not E2E.
    app.state.auth.http.close()
    app.state.data.http.close()
    app.state.auth.http = httpx.Client(
        base_url="http://auth", transport=httpx.MockTransport(respond)
    )
    app.state.data.http = httpx.Client(
        base_url="http://data", transport=httpx.MockTransport(respond)
    )
    send = Mock()
    monkeypatch.setattr(app.state.queue, "send_task", send)
    with gateway:
        headers = {"Authorization": "Bearer unit-test-only", "X-Request-ID": correlation}
        response = gateway.post("/v1/jobs", json={"description": "hello world"}, headers=headers)
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert response.headers["X-Request-ID"] == correlation
        assert send.call_args.kwargs["args"] == [str(job.id), correlation]
        assert gateway.get(f"/v1/jobs/{job.id}", headers=headers).status_code == 200
    assert seen == ["auth", "data", "auth", "data"]


def test_gateway_missing_auth(gateway: TestClient) -> None:
    with gateway:
        assert gateway.post("/v1/jobs", json={"description": "hello"}).status_code == 401
        assert gateway.get(f"/v1/jobs/{uuid4()}").status_code == 401


@pytest.mark.parametrize("dependency", ["auth", "data", "broker"])
def test_gateway_not_ready_when_dependency_fails(
    gateway: TestClient, monkeypatch: pytest.MonkeyPatch, dependency: str
) -> None:
    app = cast(FastAPI, gateway.app)
    monkeypatch.setattr(app.state.auth, "ready", Mock())
    monkeypatch.setattr(app.state.data, "ready", Mock())
    monkeypatch.setattr(app.state.broker, "ping", Mock())
    target = getattr(app.state, dependency)
    method = "ping" if dependency == "broker" else "ready"
    error = RedisConnectionError() if dependency == "broker" else UpstreamError("upstream_timeout")
    monkeypatch.setattr(target, method, Mock(side_effect=error))
    with gateway:
        assert gateway.get("/health").status_code == 200
        assert gateway.get("/ready").status_code == 503


def test_gateway_ready(gateway: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cast(FastAPI, gateway.app).state.auth, "ready", Mock())
    monkeypatch.setattr(cast(FastAPI, gateway.app).state.data, "ready", Mock())
    monkeypatch.setattr(cast(FastAPI, gateway.app).state.broker, "ping", Mock(return_value=True))
    with gateway:
        assert gateway.get("/ready").status_code == 200


@pytest.mark.parametrize("record_failure", [True, False])
def test_enqueue_failure_is_not_success(
    gateway: TestClient, monkeypatch: pytest.MonkeyPatch, record_failure: bool
) -> None:
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
    monkeypatch.setattr(
        cast(FastAPI, gateway.app).state.auth,
        "validate",
        Mock(return_value=Mock(subject="sandbox-user")),
    )
    monkeypatch.setattr(cast(FastAPI, gateway.app).state.data, "create", Mock(return_value=job))
    patch = Mock(side_effect=None if record_failure else UpstreamError("unavailable"))
    monkeypatch.setattr(cast(FastAPI, gateway.app).state.data, "patch", patch)
    monkeypatch.setattr(
        cast(FastAPI, gateway.app).state.queue,
        "send_task",
        Mock(side_effect=RuntimeError("broker failure")),
    )
    with gateway:
        response = gateway.post(
            "/v1/jobs", json={"description": "hello"}, headers={"Authorization": "Bearer test"}
        )
        assert response.status_code == 503
        assert response.json()["detail"]["job_id"] == str(job.id)
    assert patch.call_args.args[1].status == JobStatus.FAILED


def test_data_readiness_failure_and_internal_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = Mock()
    engine.connect.side_effect = OperationalError("SELECT", {}, Exception("private error"))
    monkeypatch.setattr("incidentpilot.services.data.app.create_engine", Mock(return_value=engine))
    config = DataSettings(
        database_url=SecretStr("postgresql+psycopg://test@db/test"),
        internal_token=SecretStr("unit-test-only-token"),
    )
    with TestClient(data_app(config)) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/ready")
        assert response.status_code == 503
        assert "private" not in response.text
        assert client.get(f"/v1/jobs/{uuid4()}").status_code == 401
