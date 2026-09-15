from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import ValidationError

from incidentpilot.incidents.models import EvidenceAction
from incidentpilot.shared.evidence import (
    DeploymentEvidence,
    LogsEvidence,
    MetricsEvidence,
    ServiceStatusEvidence,
    TraceEvidence,
)

Evidence = (
    DeploymentEvidence | LogsEvidence | MetricsEvidence | ServiceStatusEvidence | TraceEvidence
)


class EvidenceToolError(RuntimeError):
    pass


class EvidenceTools:
    """Only exported operational capabilities available to the investigation loop."""

    def __init__(
        self, evidence_url: str, timeout: float, transport: httpx.BaseTransport | None = None
    ):
        self.http = httpx.Client(base_url=evidence_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self.http.close()

    def execute(self, action: EvidenceAction) -> Evidence:
        path: str
        params: dict[str, Any] = {}
        models: dict[str, type[Evidence]] = {
            "get_service_status": ServiceStatusEvidence,
            "get_request_metrics": MetricsEvidence,
            "get_job_metrics": MetricsEvidence,
            "get_dependency_metrics": MetricsEvidence,
            "get_readiness_metrics": MetricsEvidence,
            "search_logs": LogsEvidence,
            "get_trace": TraceEvidence,
            "get_recent_deployments": DeploymentEvidence,
        }
        if action.tool == "get_service_status":
            path = "/v1/evidence/services"
        elif action.tool.endswith("_metrics"):
            kind = action.tool.removeprefix("get_").removesuffix("_metrics")
            path = f"/v1/evidence/metrics/{kind}"
            params = {"window_seconds": action.window_seconds}
            if action.service:
                params["service"] = action.service
        elif action.tool == "search_logs":
            if not action.service:
                raise EvidenceToolError("search_logs requires an allowlisted service")
            end = datetime.now(UTC)
            path = "/v1/evidence/logs"
            params = {
                "service": action.service,
                "start": end - timedelta(seconds=action.window_seconds),
                "end": end,
                "limit": action.limit,
            }
        elif action.tool == "get_trace":
            if not action.trace_id:
                raise EvidenceToolError("get_trace requires a validated trace ID")
            path = f"/v1/evidence/traces/{action.trace_id}"
        else:
            path = "/v1/evidence/deployments"
            params = {"limit": action.limit}
        try:
            response = self.http.get(path, params=params)
            response.raise_for_status()
            return models[action.tool].model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise EvidenceToolError("typed evidence operation failed") from exc
