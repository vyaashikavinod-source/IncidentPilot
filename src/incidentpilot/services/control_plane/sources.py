"""Explicit read-only evidence source interfaces and backend adapters."""

import json
import re
import time
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

import httpx

from incidentpilot.shared.evidence import (
    Deployment,
    DeploymentEvidence,
    LogEvent,
    LogsEvidence,
    MetricPoint,
    MetricsEvidence,
    Provenance,
    ServiceObservation,
    ServiceStatusEvidence,
    SourceType,
    TraceEvidence,
    TraceSpan,
)

SERVICES = frozenset({"gateway", "auth", "data", "worker"})
ENVIRONMENTS = frozenset({"local", "test"})
LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
SAFE_ATTRIBUTES = frozenset(
    {
        "http.request.method",
        "http.response.status_code",
        "url.path",
        "server.address",
        "db.system",
        "messaging.system",
        "error.type",
    }
)
METRICS = {
    "requests": (
        "sum(rate(incidentpilot_http_requests_total[{window}])) by (service,route,method,status)"
    ),
    "jobs": "sum(increase(incidentpilot_jobs_total[{window}])) by (service,event)",
    "dependencies": (
        "sum(rate(incidentpilot_dependency_requests_total[{window}])) "
        "by (service,dependency,outcome)"
    ),
    "readiness": "incidentpilot_readiness",
}


class EvidenceBackendError(RuntimeError):
    pass


class MetricsEvidenceSource(Protocol):
    def query(
        self, kind: str, service: str | None, window_seconds: int, request_id: UUID
    ) -> MetricsEvidence: ...


class LogEvidenceSource(Protocol):
    def query(
        self,
        service: str,
        environment: str,
        level: str | None,
        request_id_filter: str | None,
        trace_id: str | None,
        start: datetime,
        end: datetime,
        limit: int,
        request_id: UUID,
    ) -> LogsEvidence: ...


class TraceEvidenceSource(Protocol):
    def get(self, trace_id: str, request_id: UUID) -> TraceEvidence: ...


class ServiceStatusEvidenceSource(Protocol):
    def get(self, request_id: UUID) -> ServiceStatusEvidence: ...


class DeploymentEvidenceSource(Protocol):
    def get(self, limit: int, request_id: UUID) -> DeploymentEvidence: ...


def provenance(
    source_type: SourceType,
    source_name: str,
    description: str,
    count: int,
    latency: float,
    request_id: UUID,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    truncated: bool = False,
) -> Provenance:
    return Provenance(
        evidence_id=uuid4(),
        source_type=source_type,
        source_name=source_name,
        collected_at=datetime.now(UTC),
        request_description=description,
        window_start=start,
        window_end=end,
        result_count=count,
        truncated=truncated,
        backend_latency_ms=latency * 1000,
        request_id=request_id,
    )


class Backend:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.client = httpx.Client(base_url=base_url, timeout=timeout)

    def json(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[object, float]:
        started = time.monotonic()
        try:
            response = self.client.get(path, params=params, headers=headers)
            response.raise_for_status()
            return response.json(), time.monotonic() - started
        except (httpx.HTTPError, ValueError) as exc:
            raise EvidenceBackendError(type(exc).__name__) from exc


class PrometheusSource(Backend):
    def query(
        self, kind: str, service: str | None, window_seconds: int, request_id: UUID
    ) -> MetricsEvidence:
        if kind not in METRICS or service is not None and service not in SERVICES:
            raise ValueError("unsupported metric query")
        query = METRICS[kind].format(window=f"{window_seconds}s")
        if service:
            query = f'({query}) and on(service) incidentpilot_readiness{{service="{service}"}}'
        raw, latency = self.json("/api/v1/query", {"query": query})
        try:
            result = cast(dict[str, object], raw)["data"]
            series = cast(dict[str, object], result)["result"]
            points = []
            for item in cast(list[dict[str, object]], series):
                value = cast(list[object], item["value"])
                points.append(
                    MetricPoint(
                        labels=cast(dict[str, str], item["metric"]),
                        timestamp=float(cast(float | str, value[0])),
                        value=float(cast(float | str, value[1])),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceBackendError("malformed Prometheus response") from exc
        return MetricsEvidence(
            provenance=provenance(
                SourceType.METRICS,
                "prometheus",
                f"allowlisted {kind} metric evidence",
                len(points),
                latency,
                request_id,
            ),
            metric=kind,
            points=points,
        )


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(term in key.lower() for term in ("password", "secret", "token", "authorization"))
            else redact(item)
            for key, item in value.items()
        }
    return value


class LokiSource(Backend):
    def query(
        self,
        service: str,
        environment: str,
        level: str | None,
        request_id_filter: str | None,
        trace_id: str | None,
        start: datetime,
        end: datetime,
        limit: int,
        request_id: UUID,
    ) -> LogsEvidence:
        if (
            service not in SERVICES
            or environment not in ENVIRONMENTS
            or level
            and level not in LEVELS
        ):
            raise ValueError("unsupported log filter")
        selectors = [f'service_name="{service}"']
        query = "{" + ",".join(selectors) + "}"
        for key, value in (
            ("deployment_environment_name", environment),
            ("severity_text", level),
            ("request_id", request_id_filter),
            ("trace_id", trace_id),
        ):
            if value:
                safe = re.sub(r"[^A-Za-z0-9_.:-]", "", value)
                query += f' | {key} = "{safe}"'
        raw, latency = self.json(
            "/loki/api/v1/query_range",
            {
                "query": query,
                "start": str(int(start.timestamp() * 1e9)),
                "end": str(int(end.timestamp() * 1e9)),
                "limit": limit + 1,
                "direction": "backward",
            },
        )
        events: list[LogEvent] = []
        try:
            streams = cast(
                list[dict[str, object]],
                cast(dict[str, object], cast(dict[str, object], raw)["data"])["result"],
            )
            for stream in streams:
                labels = cast(dict[str, str], stream["stream"])
                for entry in cast(list[list[object]], stream["values"]):
                    timestamp, line = str(entry[0]), str(entry[1])
                    metadata = (
                        cast(dict[str, str], entry[2])
                        if len(entry) > 2 and isinstance(entry[2], dict)
                        else {}
                    )
                    try:
                        parsed = redact(json.loads(line))
                        item = cast(dict[str, object], parsed)
                    except json.JSONDecodeError:
                        item = {"message": line, "event": line}
                    known = {
                        key: item.pop(key, None) or metadata.get(key) or labels.get(key)
                        for key in (
                            "level",
                            "event",
                            "message",
                            "request_id",
                            "trace_id",
                            "span_id",
                            "service",
                        )
                    }
                    events.append(
                        LogEvent(
                            timestamp=datetime.fromtimestamp(int(timestamp) / 1e9, UTC),
                            service=str(known["service"] or labels.get("service_name", service)),
                            level=cast(str | None, known["level"]) or labels.get("severity_text"),
                            event=cast(str | None, known["event"]),
                            message=cast(str | None, known["message"]),
                            request_id=cast(str | None, known["request_id"])
                            or metadata.get("request_id")
                            or labels.get("request_id"),
                            trace_id=cast(str | None, known["trace_id"])
                            or metadata.get("trace_id")
                            or labels.get("trace_id"),
                            span_id=cast(str | None, known["span_id"])
                            or metadata.get("span_id")
                            or labels.get("span_id"),
                            attributes=item,
                        )
                    )
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceBackendError("malformed Loki response") from exc
        events.sort(key=lambda item: item.timestamp, reverse=True)
        truncated = len(events) > limit
        events = events[:limit]
        return LogsEvidence(
            provenance=provenance(
                SourceType.LOGS,
                "loki",
                "bounded structured log search",
                len(events),
                latency,
                request_id,
                start=start,
                end=end,
                truncated=truncated,
            ),
            events=events,
        )


class TempoSource(Backend):
    def get(self, trace_id: str, request_id: UUID) -> TraceEvidence:
        if not TRACE_ID.fullmatch(trace_id):
            raise ValueError("trace_id must be 32 lowercase hexadecimal characters")
        raw, latency = self.json(f"/api/traces/{trace_id}")
        spans: list[TraceSpan] = []
        try:
            for batch in cast(dict[str, list[dict[str, object]]], raw)["batches"]:
                resource = cast(dict[str, object], batch["resource"])
                attrs = {
                    item["key"]: next(iter(cast(dict[str, object], item["value"]).values()))
                    for item in cast(list[dict[str, object]], resource.get("attributes", []))
                }
                service = str(attrs.get("service.name", "unknown"))
                for scope in cast(list[dict[str, object]], batch["scopeSpans"]):
                    for span in cast(list[dict[str, object]], scope["spans"]):
                        attributes = {
                            item["key"]: next(iter(cast(dict[str, object], item["value"]).values()))
                            for item in cast(list[dict[str, object]], span.get("attributes", []))
                            if item["key"] in SAFE_ATTRIBUTES
                        }
                        spans.append(
                            TraceSpan(
                                span_id=str(span["spanId"]),
                                parent_span_id=str(span.get("parentSpanId") or "") or None,
                                service=service,
                                name=str(span["name"]),
                                start_ns=int(cast(str | int, span["startTimeUnixNano"])),
                                duration_ns=int(cast(str | int, span["endTimeUnixNano"]))
                                - int(cast(str | int, span["startTimeUnixNano"])),
                                status=str(
                                    cast(dict[str, object], span.get("status", {})).get(
                                        "code", "STATUS_CODE_UNSET"
                                    )
                                ),
                                attributes=attributes,
                            )
                        )
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceBackendError("malformed Tempo response") from exc
        return TraceEvidence(
            provenance=provenance(
                SourceType.TRACE,
                "tempo",
                "exact trace lookup",
                len(spans),
                latency,
                request_id,
                truncated=False,
            ),
            trace_id=trace_id,
            services=sorted({span.service for span in spans}),
            spans=spans[:500],
        )


class ServiceStatusSource:
    def __init__(self, urls: dict[str, str], timeout: float) -> None:
        self.urls, self.timeout = urls, timeout

    def get(self, request_id: UUID) -> ServiceStatusEvidence:
        started_all = time.monotonic()
        observations = []
        for service, url in self.urls.items():
            started = time.monotonic()
            try:
                if service == "worker":
                    response = httpx.get(f"{url}/metrics", timeout=self.timeout)
                    observations.append(
                        ServiceObservation(
                            service=service,
                            alive=response.status_code == 200,
                            ready=response.status_code == 200,
                            observed_at=datetime.now(UTC),
                            latency_ms=(time.monotonic() - started) * 1000,
                            detail=None if response.status_code == 200 else "metrics_unavailable",
                        )
                    )
                    continue
                health = httpx.get(f"{url}/health", timeout=self.timeout)
                ready = httpx.get(f"{url}/ready", timeout=self.timeout)
                observations.append(
                    ServiceObservation(
                        service=service,
                        alive=health.status_code == 200,
                        ready=ready.status_code == 200,
                        observed_at=datetime.now(UTC),
                        latency_ms=(time.monotonic() - started) * 1000,
                        detail=None if ready.status_code == 200 else "readiness_failed",
                    )
                )
            except httpx.HTTPError:
                observations.append(
                    ServiceObservation(
                        service=service,
                        alive=False,
                        ready=False,
                        observed_at=datetime.now(UTC),
                        latency_ms=(time.monotonic() - started) * 1000,
                        detail="unavailable",
                    )
                )
        return ServiceStatusEvidence(
            provenance=provenance(
                SourceType.SERVICE_STATUS,
                "allowlisted-services",
                "health and readiness",
                len(observations),
                time.monotonic() - started_all,
                request_id,
            ),
            services=observations,
        )


class DeploymentSource(Backend):
    def __init__(self, base_url: str, timeout: float, token: str) -> None:
        super().__init__(base_url, timeout)
        self.headers = {"X-Internal-Token": token}

    def get(self, limit: int, request_id: UUID) -> DeploymentEvidence:
        raw, latency = self.json("/v1/deployments", {"limit": limit}, self.headers)
        try:
            deployments = [Deployment.model_validate(item) for item in cast(list[object], raw)]
        except (TypeError, ValueError) as exc:
            raise EvidenceBackendError("malformed deployment response") from exc
        return DeploymentEvidence(
            provenance=provenance(
                SourceType.DEPLOYMENT_HISTORY,
                "data-service",
                "recent deployments",
                len(deployments),
                latency,
                request_id,
            ),
            deployments=deployments,
        )
