"""PostgreSQL persistence is owned exclusively by the data service."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from incidentpilot.shared.schemas import JobStatus


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "(status = 'completed' AND result IS NOT NULL AND error IS NULL) OR "
            "(status = 'failed' AND error IS NOT NULL AND result IS NULL) OR "
            "(status IN ('queued', 'running') AND result IS NULL AND error IS NULL)",
            name="job_outcome",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(String(1000))
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            values_callable=lambda values: [value.value for value in values],
            native_enum=False,
            create_constraint=True,
            name="job_status",
        ),
        default=JobStatus.QUEUED,
    )
    result: Mapped[dict[str, int | str] | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeploymentRecord(Base):
    __tablename__ = "deployments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service: Mapped[str] = mapped_column(String(63), index=True)
    version: Mapped[str] = mapped_column(String(100))
    git_sha: Mapped[str] = mapped_column(String(64))
    image_reference: Mapped[str] = mapped_column(String(255))
    environment: Mapped[str] = mapped_column(String(32), index=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32))
    deployment_metadata: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
