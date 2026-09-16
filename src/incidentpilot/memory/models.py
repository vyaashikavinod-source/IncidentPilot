from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentMemory(StrictModel):
    memory_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    affected_service: str = Field(min_length=1, max_length=63)
    failure_class: str = Field(min_length=1, max_length=100)
    root_cause_summary: str = Field(min_length=1, max_length=1000)
    investigation_summary: str = Field(min_length=1, max_length=3000)
    remediation_proposal_summary: str = Field(min_length=1, max_length=1000)
    outcome: str | None = Field(default=None, max_length=500)
    evidence_categories: tuple[str, ...] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1)
    tags: tuple[str, ...] = Field(default=(), max_length=12)
    source_version: str = Field(default="incidentpilot-memory-v1", max_length=64)
    benchmark_tagged: bool = False

    @field_validator("tags", "evidence_categories")
    @classmethod
    def bounded_labels(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 63 for item in values):
            raise ValueError("memory labels must be bounded")
        return tuple(dict.fromkeys(values))


class MemoryQuery(StrictModel):
    affected_service: str | None = Field(default=None, max_length=63)
    failure_class: str | None = Field(default=None, max_length=100)
    tags: tuple[str, ...] = Field(default=(), max_length=6)
    limit: int = Field(default=5, ge=1, le=10)


class MemorySearchResult(StrictModel):
    memory: IncidentMemory
    score: int = Field(ge=0)
