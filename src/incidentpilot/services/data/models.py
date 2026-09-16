"""PostgreSQL persistence is owned exclusively by the data service."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
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
        UniqueConstraint("owner_id", "idempotency_key", name="uq_jobs_owner_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(String(1000))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_sha256: Mapped[str] = mapped_column(String(64))
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


class IncidentRecord(Base):
    __tablename__ = "incidents"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    document: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditRecordRow(Base):
    __tablename__ = "incident_audit_records"
    __table_args__ = (
        UniqueConstraint("incident_id", "sequence", name="uq_audit_incident_sequence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    chain_version: Mapped[int] = mapped_column(Integer)
    canonicalization_version: Mapped[str] = mapped_column(String(64))
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(200))
    event_metadata: Mapped[dict[str, object]] = mapped_column(JSONB)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)


class AuditCheckpointRow(Base):
    __tablename__ = "audit_checkpoints"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    checkpoint_version: Mapped[int] = mapped_column(Integer)
    last_sequence: Mapped[int] = mapped_column(Integer)
    last_record_hash: Mapped[str] = mapped_column(String(64))
    checkpoint_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signature: Mapped[str] = mapped_column(String(64), unique=True)
