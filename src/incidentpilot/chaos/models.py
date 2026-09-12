"""Typed public scenario, private ground-truth, and run provenance contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FailureClass(StrEnum):
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    SERVICE_UNAVAILABLE = "service_unavailable"
    PROCESSING_DELAY = "processing_delay"
    OBSERVABILITY_DEGRADED = "observability_degraded"


class InjectionMethod(StrEnum):
    COMPOSE_STOP = "compose_stop"
    COMPOSE_PAUSE = "compose_pause"


class Scenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=3, max_length=100)
    version: str = Field(pattern=r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
    description: str = Field(min_length=10, max_length=500)
    affected_service: Literal[
        "postgres",
        "redis",
        "worker",
        "auth",
        "data",
        "gateway",
        "otel-collector",
        "prometheus",
        "tempo",
    ]
    failure_class: FailureClass
    severity: Literal["low", "medium", "high", "critical"]
    injection_method: InjectionMethod
    expected_start_condition: str
    expected_observable_signals: tuple[str, ...] = Field(min_length=1)
    recovery_action: str
    recovery_condition: str
    maximum_duration_seconds: int = Field(ge=10, le=300)
    cleanup_requirements: tuple[str, ...] = Field(min_length=1)


class GroundTruth(StrictModel):
    scenario_id: str
    scenario_version: str
    root_cause_class: str = Field(min_length=3)
    ground_truth_root_cause: str = Field(min_length=10)
    acceptable_diagnoses: tuple[str, ...] = Field(min_length=1)
    misleading_or_irrelevant_signals: tuple[str, ...] = ()
    affected_service: str
    failure_class: FailureClass


class EvidenceSnapshot(StrictModel):
    captured_at: datetime
    window_start: datetime
    window_end: datetime
    responses: dict[str, dict[str, object]]


class RunManifest(StrictModel):
    run_id: UUID
    scenario_id: str
    scenario_version: str
    repository_commit: str
    started_at: datetime
    injection_timestamp: datetime | None = None
    recovery_timestamp: datetime | None = None
    affected_service: str
    injection_result: Literal["pending", "succeeded", "failed"] = "pending"
    recovery_result: Literal["pending", "succeeded", "failed"] = "pending"
    sandbox_versions: dict[str, str]
    evidence_window_start: datetime
    evidence_window_end: datetime | None = None
    ground_truth_reference: str
    scenario_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ground_truth_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_status: Literal["starting", "active", "recovered", "failed"] = "starting"

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> "RunManifest":
        if self.recovery_timestamp and not self.injection_timestamp:
            raise ValueError("recovery cannot precede injection")
        if self.injection_timestamp and self.injection_timestamp < self.started_at:
            raise ValueError("injection timestamp precedes run start")
        return self
