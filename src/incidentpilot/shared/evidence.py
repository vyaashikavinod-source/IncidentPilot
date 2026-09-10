"""Typed operational evidence contracts with provenance."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    METRICS = "metrics"
    LOGS = "logs"
    TRACE = "trace"
    SERVICE_STATUS = "service_status"
    DEPLOYMENT_HISTORY = "deployment_history"


class Provenance(BaseModel):
    evidence_id: UUID
    source_type: SourceType
    source_name: str
    collected_at: datetime
    request_description: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    result_count: int = Field(ge=0)
    truncated: bool
    backend_latency_ms: float = Field(ge=0)
    request_id: UUID


class MetricPoint(BaseModel):
    labels: dict[str, str]
    timestamp: float
    value: float


class MetricsEvidence(BaseModel):
    provenance: Provenance
    metric: str
    points: list[MetricPoint]


class LogEvent(BaseModel):
    timestamp: datetime
    service: str
    level: str | None = None
    event: str | None = None
    message: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class LogsEvidence(BaseModel):
    provenance: Provenance
    events: list[LogEvent]


class TraceSpan(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    service: str
    name: str
    start_ns: int
    duration_ns: int
    status: str
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class TraceEvidence(BaseModel):
    provenance: Provenance
    trace_id: str
    services: list[str]
    spans: list[TraceSpan]


class ServiceObservation(BaseModel):
    service: str
    alive: bool
    ready: bool | None
    observed_at: datetime
    latency_ms: float
    detail: str | None = None


class ServiceStatusEvidence(BaseModel):
    provenance: Provenance
    services: list[ServiceObservation]


class Deployment(BaseModel):
    deployment_id: UUID
    service: str
    version: str
    git_sha: str
    image_reference: str
    environment: str
    deployed_at: datetime
    status: Literal["succeeded", "failed", "rolled_back"]
    metadata: dict[str, str] = Field(default_factory=dict)


class DeploymentEvidence(BaseModel):
    provenance: Provenance
    deployments: list[Deployment]
