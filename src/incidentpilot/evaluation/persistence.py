from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ManualBenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_run_id: UUID = Field(default_factory=uuid4)
    evaluation_run_id: UUID | None = None
    participant_pseudonym: str = Field(min_length=1, max_length=100)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    submitted_root_cause: str | None = Field(default=None, max_length=1000)
    affected_service: str | None = Field(default=None, max_length=63)
    failure_class: str | None = Field(default=None, max_length=100)
    evidence_references: tuple[str, ...] = ()
    finalized: bool = False
    score: dict[str, bool] | None = None
    scorer_version: str | None = Field(default=None, max_length=100)
    scored_at: datetime | None = None

    @model_validator(mode="after")
    def finalized_complete(self) -> "ManualBenchmarkRun":
        if self.finalized and (
            not self.completed_at or not self.submitted_root_cause or self.duration_seconds is None
        ):
            raise ValueError("finalized manual runs require completed diagnosis")
        return self


class EvaluationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_run_id: UUID = Field(default_factory=uuid4)
    repository_commit: str = Field(min_length=7, max_length=64)
    provider: str
    model: str
    memory_enabled: bool
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    agent_version: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=100)
    scenario_results: list["EvaluationScenarioResult"] = Field(default_factory=list, max_length=9)

    @model_validator(mode="after")
    def completed_consistency(self) -> "EvaluationRun":
        if self.status == "completed" and (self.completed_at is None or not self.scenario_results):
            raise ValueError("completed evaluation runs require results and a completion timestamp")
        if self.status != "completed" and self.completed_at is not None:
            raise ValueError("only completed evaluation runs may have a completion timestamp")
        return self


class EvaluationScenarioResult(BaseModel):
    """Scored fixture or real-agent outcome; it deliberately contains no hidden truth."""

    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=100)
    chaos_run_id: UUID | None = None
    incident_id: UUID | None = None
    root_cause_correct: bool
    affected_service_correct: bool
    failure_class_correct: bool
    confidence: float = Field(ge=0, le=1)
    evidence_references: tuple[str, ...] = Field(default=(), max_length=100)
    memory_references: tuple[UUID, ...] = Field(default=(), max_length=20)
    unsupported_reference: bool = False
    investigation_turns: int = Field(ge=0)
    evidence_calls: int = Field(ge=0)
    memory_calls: int = Field(ge=0)
    provider_calls: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    input_cost: float | None = Field(default=None, ge=0)
    output_cost: float | None = Field(default=None, ge=0)
    total_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    duration_seconds: float = Field(ge=0)
    proposal_type: str | None = Field(default=None, max_length=100)
    recovery_result: str | None = Field(default=None, max_length=100)
    affected_service: str | None = Field(default=None, max_length=63)
    failure_class: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def totals_are_consistent(self) -> "EvaluationScenarioResult":
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        if (
            self.total_cost is not None
            and self.input_cost is not None
            and self.output_cost is not None
            and abs(self.total_cost - (self.input_cost + self.output_cost)) > 1e-9
        ):
            raise ValueError("total_cost must equal input_cost plus output_cost")
        if self.currency is not None and self.total_cost is None:
            raise ValueError("currency requires a total_cost")
        return self
