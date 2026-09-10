from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from incidentpilot.services.control_plane.app import create_app
from incidentpilot.services.control_plane.sources import (
    EvidenceBackendError,
    LokiSource,
    PrometheusSource,
    TempoSource,
)
from incidentpilot.shared.config import ControlPlaneSettings


def client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="http://backend")


def test_prometheus_builds_only_allowlisted_query() -> None:
    seen = ""

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request.url.params["query"]
        return httpx.Response(
            200, json={"data": {"result": [{"metric": {"service": "gateway"}, "value": [1, "2"]}]}}
        )

    source = PrometheusSource("http://backend", 1)
    source.client = client(httpx.MockTransport(respond))
    result = source.query("jobs", "gateway", 900, uuid4())
    assert "incidentpilot_jobs_total[900s]" in seen
    assert 'service="gateway"' in seen
    assert result.points[0].value == 2
    with pytest.raises(ValueError):
        source.query("raw", None, 900, uuid4())


def test_loki_builds_filters_limits_and_redacts() -> None:
    seen = httpx.URL("http://unset")

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request.url
        line = (
            '{"service":"gateway","level":"ERROR","request_id":"abc",'
            '"token":"leak","message":"failed"}'
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "result": [
                        {
                            "stream": {"service_name": "gateway"},
                            "values": [["1000000000", line], ["2000000000", line]],
                        }
                    ]
                }
            },
        )

    source = LokiSource("http://backend", 1)
    source.client = client(httpx.MockTransport(respond))
    end = datetime.now(UTC)
    result = source.query(
        "gateway", "local", "ERROR", "abc", None, end - timedelta(minutes=1), end, 1, uuid4()
    )
    assert 'service_name="gateway"' in seen.params["query"]
    assert seen.params["limit"] == "2"
    assert result.provenance.truncated is True
    assert result.events[0].attributes["token"] == "[REDACTED]"


def test_tempo_validates_and_parses_bounded_safe_span() -> None:
    source = TempoSource("http://backend", 1)
    source.client = client(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "batches": [
                        {
                            "resource": {
                                "attributes": [
                                    {"key": "service.name", "value": {"stringValue": "gateway"}}
                                ]
                            },
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "spanId": "01",
                                            "name": "GET /ready",
                                            "startTimeUnixNano": "10",
                                            "endTimeUnixNano": "20",
                                            "attributes": [
                                                {
                                                    "key": "http.response.status_code",
                                                    "value": {"intValue": 200},
                                                },
                                                {"key": "secret", "value": {"stringValue": "no"}},
                                            ],
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
        )
    )
    trace = source.get("a" * 32, uuid4())
    assert trace.services == ["gateway"]
    assert trace.spans[0].duration_ns == 10
    assert "secret" not in trace.spans[0].attributes
    with pytest.raises(ValueError):
        source.get("not-a-trace", uuid4())


def test_backend_timeout_non_2xx_and_malformed_are_not_empty() -> None:
    for response in (
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("late")),
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, json={"wrong": True}),
    ):
        source = PrometheusSource("http://backend", 1)
        source.client = client(httpx.MockTransport(response))
        with pytest.raises(EvidenceBackendError):
            source.query("readiness", None, 60, uuid4())


def test_control_plane_openapi_is_read_only_and_request_id_is_preserved() -> None:
    settings = ControlPlaneSettings(
        environment="test",
        service_name="control-plane",
        internal_token="x" * 32,
    )
    app = create_app(settings)
    paths = app.openapi()["paths"]
    assert paths
    assert {method for operations in paths.values() for method in operations} <= {"get"}
    assert not any(
        "url" in parameter["name"]
        for operations in paths.values()
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
    )
    correlation = str(uuid4())
    with TestClient(app) as test_client:
        response = test_client.get(
            "/v1/evidence/traces/not-valid", headers={"X-Request-ID": correlation}
        )
    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == correlation


def test_control_plane_rejects_unsafe_services_windows_and_limits() -> None:
    app = create_app(
        ControlPlaneSettings(
            environment="test", service_name="control-plane", internal_token="x" * 32
        )
    )
    with TestClient(app) as test_client:
        assert (
            test_client.get(
                "/v1/evidence/metrics/requests", params={"service": "arbitrary"}
            ).status_code
            == 422
        )
        assert (
            test_client.get(
                "/v1/evidence/metrics/jobs", params={"window_seconds": 86401}
            ).status_code
            == 422
        )
        assert (
            test_client.get(
                "/v1/evidence/logs", params={"service": "gateway", "limit": 501}
            ).status_code
            == 422
        )
