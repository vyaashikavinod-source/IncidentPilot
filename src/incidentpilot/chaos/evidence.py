"""Evidence capture exclusively through the existing read-only control plane."""

from datetime import UTC, datetime, timedelta

import httpx

from incidentpilot.chaos.models import EvidenceSnapshot, Scenario


def capture_evidence(base_url: str, scenario: Scenario, timeout: float = 10) -> EvidenceSnapshot:
    end = datetime.now(UTC)
    start = end - timedelta(seconds=min(scenario.maximum_duration_seconds + 60, 900))
    requests: dict[str, tuple[str, dict[str, str | int]]] = {
        "control_plane_readiness": ("/ready", {}),
        "services": ("/v1/evidence/services", {}),
        "deployments": ("/v1/evidence/deployments", {"limit": 20}),
        "readiness_metrics": (
            "/v1/evidence/metrics/readiness",
            {"window_seconds": 900},
        ),
        "dependency_metrics": (
            "/v1/evidence/metrics/dependencies",
            {"window_seconds": 900},
        ),
        "logs": (
            "/v1/evidence/logs",
            {
                "service": scenario.affected_service
                if scenario.affected_service in {"gateway", "auth", "data", "worker"}
                else "gateway",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 100,
            },
        ),
    }
    responses: dict[str, dict[str, object]] = {}
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for name, (path, params) in requests.items():
            try:
                response = client.get(path, params=params)
                responses[name] = {
                    "status_code": response.status_code,
                    "body": response.json(),
                }
            except (httpx.HTTPError, ValueError) as exc:
                responses[name] = {"status_code": 0, "error": type(exc).__name__}
    return EvidenceSnapshot(
        captured_at=end, window_start=start, window_end=end, responses=responses
    )
