from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    DIAGNOSED = "diagnosed"
    PROPOSAL_READY = "proposal_ready"
    APPROVED = "approved"
    CLOSED = "closed"


class IncidentCreate(StrictModel):
    source: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    severity: Literal["low", "medium", "high", "critical"]
    affected_service_hint: str | None = Field(default=None, max_length=63)
    alert_metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("alert_metadata")
    @classmethod
    def bounded_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20 or any(
            not key or len(key) > 100 or len(item) > 500 for key, item in value.items()
        ):
            raise ValueError("alert metadata exceeds bounded key/value limits")
        return value


class EvidenceAction(StrictModel):
    tool: Literal[
        "get_service_status",
        "get_request_metrics",
        "get_job_metrics",
        "get_dependency_metrics",
        "get_readiness_metrics",
        "search_logs",
        "get_trace",
        "get_recent_deployments",
    ]
    service: Literal["gateway", "auth", "data", "worker"] | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    window_seconds: int = Field(default=300, ge=60, le=3600)
    limit: int = Field(default=50, ge=1, le=100)


class HypothesisDisposition(StrEnum):
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class InvestigationStep(StrictModel):
    step_number: int = Field(ge=1)
    timestamp: datetime
    current_hypothesis: str = Field(min_length=1, max_length=1000)
    requested_evidence_action: EvidenceAction
    evidence_ids: tuple[UUID, ...]
    observation: str = Field(min_length=1, max_length=2000)
    disposition: HypothesisDisposition


class Diagnosis(StrictModel):
    diagnosis_id: UUID = Field(default_factory=uuid4)
    likely_root_cause: str = Field(min_length=1, max_length=1000)
    affected_service: str = Field(min_length=1, max_length=63)
    failure_class: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    concise_explanation: str = Field(min_length=1, max_length=2000)
    supporting_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    contradicting_evidence_ids: tuple[UUID, ...] = ()
    remaining_uncertainties: tuple[str, ...] = ()
    investigation_summary: str = Field(min_length=1, max_length=3000)


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RemediationProposal(StrictModel):
    proposal_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    diagnosis_reference: UUID
    proposed_action_type: Literal[
        "restart_service",
        "rollback_deployment",
        "restore_dependency",
        "scale_worker",
        "configuration_change",
        "investigate_manually",
    ]
    target_service: str = Field(min_length=1, max_length=63)
    description: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
    expected_effect: str = Field(min_length=1, max_length=1000)
    risk: str = Field(min_length=1, max_length=1000)
    rollback_plan: str = Field(min_length=1, max_length=1000)
    verification_plan: str = Field(min_length=1, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ProposalStatus = ProposalStatus.PROPOSED


class ApprovalRecord(StrictModel):
    approval_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver_identity: str = Field(min_length=1, max_length=200)
    decision: Literal["approved", "rejected"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Incident(StrictModel):
    incident_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str
    title: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    affected_service_hint: str | None = None
    alert_metadata: dict[str, str] = Field(default_factory=dict)
    status: IncidentStatus = IncidentStatus.OPEN
    investigation_started_at: datetime | None = None
    investigation_completed_at: datetime | None = None
    investigation_steps: list[InvestigationStep] = Field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)
    diagnosis: Diagnosis | None = None
    remediation_proposals: list[RemediationProposal] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    audit_references: list[UUID] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    investigation_turns: int = 0
    tool_call_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None

    @field_validator("alert_metadata")
    @classmethod
    def bounded_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        return IncidentCreate.bounded_metadata(value)

    @model_validator(mode="after")
    def ordered_times(self) -> "Incident":
        if (
            self.investigation_started_at
            and self.investigation_completed_at
            and self.investigation_completed_at < self.investigation_started_at
        ):
            raise ValueError("investigation completion precedes start")
        return self


class DecisionRequest(StrictModel):
    approver_identity: str = Field(min_length=1, max_length=200)
