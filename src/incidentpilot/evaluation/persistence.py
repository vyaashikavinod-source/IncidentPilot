from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ManualBenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_run_id: UUID = Field(default_factory=uuid4)
    evaluation_run_id: UUID | None = None
    participant_pseudonym: str = Field(min_length=1, max_length=100)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
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
        if self.finalized and (not self.completed_at or not self.submitted_root_cause):
            raise ValueError("finalized manual runs require completed diagnosis")
        return self


class EvaluationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_run_id: UUID = Field(default_factory=uuid4)
    repository_commit: str = Field(min_length=7, max_length=64)
    provider: str
    model: str
    memory_enabled: bool
    scenario_results: list[dict[str, object]] = Field(default_factory=list, max_length=9)
