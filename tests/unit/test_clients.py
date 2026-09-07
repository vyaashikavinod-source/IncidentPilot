from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from incidentpilot.shared.clients import AuthClient, DataClient, ServiceClient, UpstreamError
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.schemas import Job, JobCreate, JobPatch, JobStatus


def sample_job() -> Job:
    return Job(
        id=uuid4(),
        owner_id="sandbox-user",
        description="hello world",
        status=JobStatus.QUEUED,
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("status", [301, 401, 404, 429, 500, 503])
def test_http_errors_are_explicit(status: int) -> None:
    client = ServiceClient("http://test", 1, httpx.MockTransport(lambda r: httpx.Response(status)))
    try:
        with pytest.raises(UpstreamError) as error:
            client.ready()
        assert error.value.status == status
        assert error.value.retryable == (status in {429, 500, 503})
    finally:
        client.close()


@pytest.mark.parametrize("timeout", [True, False])
def test_transport_errors(timeout: bool) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        if timeout:
            raise httpx.ReadTimeout("private detail", request=request)
        raise httpx.ConnectError("private detail", request=request)

    client = ServiceClient("http://test", 1, httpx.MockTransport(fail))
    with pytest.raises(UpstreamError) as error:
        client.ready()
    assert error.value.retryable
    assert "private detail" not in str(error.value)
    client.close()


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"status":"unavailable"}'])
def test_malformed_readiness(body: bytes) -> None:
    client = ServiceClient(
        "http://test", 1, httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    with pytest.raises(UpstreamError):
        client.ready()
    client.close()


def test_successful_readiness() -> None:
    client = ServiceClient(
        "http://test",
        1,
        httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ready"})),
    )
    client.ready()
    client.close()


@pytest.mark.parametrize("body", [b"bad-json", b"{}"])
def test_invalid_auth_response(body: bytes) -> None:
    client = AuthClient(
        "http://auth", 1, httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    with pytest.raises(UpstreamError, match="malformed"):
        client.validate("Bearer unit-test-only")
    client.close()


@pytest.mark.parametrize("authenticated", [True, False])
def test_typed_identity(authenticated: bool) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer unit-test-only"
        return httpx.Response(
            200,
            json={
                "subject": "sandbox-user",
                "roles": ["sandbox_user"],
                "authenticated": authenticated,
            },
        )

    client = AuthClient("http://auth", 1, httpx.MockTransport(respond))
    if authenticated:
        assert client.validate("Bearer unit-test-only").subject == "sandbox-user"
    else:
        with pytest.raises(UpstreamError) as error:
            client.validate("Bearer unit-test-only")
        assert error.value.status == 401
    client.close()


def test_data_contract_and_request_id_propagation() -> None:
    job = sample_job()
    seen: list[str] = []
    correlation = str(uuid4())

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Request-ID"] == correlation
        assert request.headers["X-Internal-Token"] == "unit-test-only"
        seen.append(request.method)
        return httpx.Response(200, json=job.model_dump(mode="json"))

    client = DataClient("http://data", 1, "unit-test-only", httpx.MockTransport(respond))
    token = request_id.set(correlation)
    try:
        assert client.create(JobCreate(owner_id=job.owner_id, description=job.description)) == job
        assert client.get(job.id) == job
        assert client.patch(job.id, JobPatch(status=JobStatus.RUNNING)) == job
        assert seen == ["POST", "GET", "PATCH"]
    finally:
        request_id.reset(token)
        client.close()
