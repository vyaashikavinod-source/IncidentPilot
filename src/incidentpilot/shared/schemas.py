"""Versioned HTTP contracts shared across service boundaries."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Identity(Contract):
    subject: str = Field(min_length=1, max_length=100)
    roles: list[Literal["sandbox_user"]]
    authenticated: bool


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobInput(Contract):
    description: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class JobCreate(JobInput):
    owner_id: str = Field(min_length=1, max_length=100)


class JobSubmissionCreate(JobCreate):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class JobResult(Contract):
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class JobPatch(Contract):
    status: JobStatus
    result: JobResult | None = None
    error: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_outcome(self) -> Self:
        if self.status == JobStatus.COMPLETED:
            if self.result is None or self.error is not None:
                raise ValueError("completed requires result and no error")
        elif self.status == JobStatus.FAILED:
            if self.error is None or self.result is not None:
                raise ValueError("failed requires error and no result")
        elif self.result is not None or self.error is not None:
            raise ValueError("unfinished jobs cannot have an outcome")
        return self


class Job(JobCreate):
    id: UUID
    status: JobStatus
    result: JobResult | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class JobSubmission(Contract):
    job: Job
    replayed: bool


def transition_allowed(current: JobStatus, target: JobStatus) -> bool:
    return (
        target
        in {
            JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
            JobStatus.RUNNING: {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED},
            JobStatus.COMPLETED: set(),
            JobStatus.FAILED: set(),
        }[current]
    )
