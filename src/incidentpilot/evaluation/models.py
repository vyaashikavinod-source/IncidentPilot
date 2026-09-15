from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagnosisSubmission(StrictModel):
    run_id: UUID
    scenario_id: str
    submitted_root_cause: str = Field(min_length=1)
    submitted_affected_service: str = Field(min_length=1)
    submitted_failure_class: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = ()
    diagnosis_started_at: datetime
    diagnosis_completed_at: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def completion_follows_start(self) -> "DiagnosisSubmission":
        if self.diagnosis_completed_at < self.diagnosis_started_at:
            raise ValueError("diagnosis completion precedes start")
        return self


class ManualDiagnosis(DiagnosisSubmission):
    participant_id: str = Field(min_length=1, max_length=100)


class Score(StrictModel):
    run_id: UUID
    scenario_id: str
    root_cause_correct: bool
    affected_service_correct: bool
    failure_class_correct: bool
    diagnosis_latency_seconds: float = Field(ge=0)
    evidence_reference_count: int = Field(ge=0)
    unsupported_evidence_references: tuple[str, ...]
    passed: bool


class AggregateReport(StrictModel):
    scenario_count: int
    accuracy: float
    scenario_pass_rate: float
    median_diagnosis_time_seconds: float
    failure_breakdown: dict[str, int]


class AgentScenarioResult(StrictModel):
    score: Score
    provider: str
    model: str
    confidence: float = Field(ge=0, le=1)
    investigation_turns: int = Field(ge=1)
    tool_call_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    proposal_produced: bool


class AgentAggregateReport(StrictModel):
    scenario_count: int = Field(ge=1)
    root_cause_accuracy: float = Field(ge=0, le=1)
    affected_service_accuracy: float = Field(ge=0, le=1)
    failure_class_accuracy: float = Field(ge=0, le=1)
    scenario_pass_rate: float = Field(ge=0, le=1)
    median_investigation_time_seconds: float = Field(ge=0)
    p95_investigation_time_seconds: float = Field(ge=0)
    median_tool_calls: float = Field(ge=0)
    unsupported_evidence_reference_rate: float = Field(ge=0, le=1)
    failures: tuple[str, ...]
