import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from incidentpilot.evaluation.persistence import EvaluationRun, ManualBenchmarkRun
from incidentpilot.incidents.approval import proposal_hash
from incidentpilot.incidents.audit import (
    AuditAppend,
    AuditCheckpoint,
    AuditRecord,
    ChainVerification,
    create_checkpoint,
    make_record,
    verify_chain_report,
    verify_checkpoint,
)
from incidentpilot.incidents.models import (
    ApprovalDecisionCommand,
    ApprovalRecord,
    Incident,
    IncidentStatus,
    ProposalStatus,
)
from incidentpilot.memory.models import IncidentMemory, MemoryQuery, MemorySearchResult
from incidentpilot.memory.ranking import rank_memory
from incidentpilot.services.data.models import (
    AuditCheckpointRow,
    AuditRecordRow,
    DeploymentRecord,
    EvaluationRunRow,
    IncidentMemoryRow,
    IncidentRecord,
    JobRecord,
    ManualBenchmarkRow,
)
from incidentpilot.shared.config import DataSettings
from incidentpilot.shared.evidence import Deployment
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics
from incidentpilot.shared.schemas import (
    Job,
    JobPatch,
    JobSubmission,
    JobSubmissionCreate,
    transition_allowed,
)
from incidentpilot.shared.telemetry import configure_telemetry


def create_app(settings: DataSettings | None = None) -> FastAPI:
    config = settings or DataSettings()
    metrics = Metrics(config.service_name)
    engine = create_engine(
        config.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=3,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    )
    sessions = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config)
        try:
            yield
        finally:
            engine.dispose()
            telemetry.shutdown()

    app = FastAPI(title="IncidentPilot data", lifespan=lifespan)
    telemetry = configure_telemetry(config, app)
    if config.telemetry_enabled:
        SQLAlchemyInstrumentor().instrument(engine=engine)
    configure_http(app)
    metrics.install(app)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "database_unavailable"})

    def internal(x_internal_token: Annotated[str | None, Header()] = None) -> None:
        if not secrets.compare_digest(
            (x_internal_token or "").encode(), config.internal_token.get_secret_value().encode()
        ):
            raise HTTPException(401, "internal credential required")

    def incident_internal(x_incident_token: Annotated[str | None, Header()] = None) -> None:
        if not secrets.compare_digest(
            (x_incident_token or "").encode(),
            config.incident_token.get_secret_value().encode(),
        ):
            raise HTTPException(401, "incident credential required")

    @app.get("/ready")
    def ready() -> dict[str, str]:
        started = time.monotonic()
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM jobs LIMIT 0"))
            metrics.readiness.labels(config.service_name).set(1)
        except SQLAlchemyError:
            metrics.readiness.labels(config.service_name).set(0)
            raise
        finally:
            metrics.database.labels(config.service_name, "readiness").observe(
                time.monotonic() - started
            )
        return {"status": "ready"}

    @app.post("/v1/jobs", status_code=201, dependencies=[Depends(internal)])
    def create(body: JobSubmissionCreate) -> JobSubmission:
        def existing() -> JobRecord | None:
            with sessions() as session:
                return session.scalar(
                    select(JobRecord).where(
                        JobRecord.owner_id == body.owner_id,
                        JobRecord.idempotency_key == body.idempotency_key,
                    )
                )

        record = existing()
        if record is not None:
            if record.payload_sha256 != body.payload_sha256:
                raise HTTPException(409, "idempotency_payload_conflict") from None
            return JobSubmission(job=Job.model_validate(record), replayed=True)
        try:
            with sessions.begin() as session:
                record = JobRecord(
                    owner_id=body.owner_id,
                    description=body.description,
                    idempotency_key=body.idempotency_key,
                    payload_sha256=body.payload_sha256,
                )
                session.add(record)
                session.flush()
                return JobSubmission(job=Job.model_validate(record), replayed=False)
        except IntegrityError:
            record = existing()
            if record is None:
                raise
            if record.payload_sha256 != body.payload_sha256:
                raise HTTPException(409, "idempotency_payload_conflict") from None
            return JobSubmission(job=Job.model_validate(record), replayed=True)

    def find(session: Session, job_id: UUID, lock: bool = False) -> JobRecord:
        query = select(JobRecord).where(JobRecord.id == job_id)
        if lock:
            query = query.with_for_update()
        record = session.scalar(query)
        if record is None:
            raise HTTPException(404, "job_not_found")
        return record

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(internal)])
    def get(job_id: UUID) -> Job:
        with sessions() as session:
            return Job.model_validate(find(session, job_id))

    @app.get("/v1/deployments", dependencies=[Depends(internal)])
    def deployments(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[Deployment]:
        with sessions() as session:
            rows = session.scalars(
                select(DeploymentRecord).order_by(DeploymentRecord.deployed_at.desc()).limit(limit)
            )
            return [
                Deployment(
                    deployment_id=row.id,
                    service=row.service,
                    version=row.version,
                    git_sha=row.git_sha,
                    image_reference=row.image_reference,
                    environment=row.environment,
                    deployed_at=row.deployed_at,
                    status=cast(Literal["succeeded", "failed", "rolled_back"], row.status),
                    metadata=row.deployment_metadata,
                )
                for row in rows
            ]

    @app.patch("/v1/jobs/{job_id}", dependencies=[Depends(internal)])
    def patch(job_id: UUID, body: JobPatch) -> Job:
        with sessions.begin() as session:
            record = find(session, job_id, lock=True)
            result = body.result.model_dump() if body.result else None
            if (
                record.status == body.status
                and record.result == result
                and record.error == body.error
            ):
                return Job.model_validate(record)
            if not transition_allowed(record.status, body.status):
                raise HTTPException(409, "invalid_job_transition")
            record.status, record.result, record.error = body.status, result, body.error
            record.updated_at = datetime.now(UTC)
            session.flush()
            return Job.model_validate(record)

    def find_incident(session: Session, incident_id: UUID, lock: bool = False) -> IncidentRecord:
        query = select(IncidentRecord).where(IncidentRecord.id == incident_id)
        if lock:
            query = query.with_for_update()
        record = session.scalar(query)
        if record is None:
            raise HTTPException(404, "incident_not_found")
        return record

    @app.post("/v1/incidents", status_code=201, dependencies=[Depends(incident_internal)])
    def create_incident(body: Incident) -> Incident:
        with sessions.begin() as session:
            if session.get(IncidentRecord, body.incident_id):
                raise HTTPException(409, "incident_exists")
            session.add(IncidentRecord(id=body.incident_id, document=body.model_dump(mode="json")))
        return body

    @app.get("/v1/incidents/{incident_id}", dependencies=[Depends(incident_internal)])
    def get_incident(incident_id: UUID) -> Incident:
        with sessions() as session:
            return Incident.model_validate(find_incident(session, incident_id).document)

    @app.put("/v1/incidents/{incident_id}", dependencies=[Depends(incident_internal)])
    def update_incident(incident_id: UUID, body: Incident) -> Incident:
        if incident_id != body.incident_id:
            raise HTTPException(422, "incident_identity_mismatch")
        with sessions.begin() as session:
            record = find_incident(session, incident_id, lock=True)
            record.document = body.model_dump(mode="json")
            record.updated_at = datetime.now(UTC)
        return body

    @app.post(
        "/v1/incidents/{incident_id}/audit",
        status_code=201,
        dependencies=[Depends(incident_internal)],
    )
    def append_audit(incident_id: UUID, body: AuditAppend) -> AuditRecord:
        with sessions.begin() as session:
            find_incident(session, incident_id, lock=True)
            previous = session.scalar(
                select(AuditRecordRow)
                .where(AuditRecordRow.incident_id == incident_id)
                .order_by(AuditRecordRow.sequence.desc())
                .limit(1)
            )
            item = make_record(
                sequence=(previous.sequence + 1 if previous else 1),
                event_type=body.event_type,
                incident_id=incident_id,
                actor=body.actor,
                metadata=body.metadata,
                previous_hash=previous.record_hash if previous else None,
            )
            session.add(
                AuditRecordRow(
                    id=item.audit_id,
                    chain_version=item.chain_version,
                    canonicalization_version=item.canonicalization_version,
                    incident_id=incident_id,
                    sequence=item.sequence,
                    timestamp=item.timestamp,
                    event_type=item.event_type,
                    actor=item.actor,
                    event_metadata=item.metadata,
                    previous_hash=item.previous_hash,
                    record_hash=item.record_hash,
                )
            )
        return item

    @app.get("/v1/incidents/{incident_id}/audit", dependencies=[Depends(incident_internal)])
    def get_audit(incident_id: UUID) -> list[AuditRecord]:
        with sessions() as session:
            find_incident(session, incident_id)
            rows = session.scalars(
                select(AuditRecordRow)
                .where(AuditRecordRow.incident_id == incident_id)
                .order_by(AuditRecordRow.sequence)
            )
            return [
                AuditRecord(
                    audit_id=row.id,
                    chain_version=row.chain_version,
                    canonicalization_version=row.canonicalization_version,
                    sequence=row.sequence,
                    timestamp=row.timestamp,
                    event_type=row.event_type,
                    incident_id=row.incident_id,
                    actor=row.actor,
                    metadata=row.event_metadata,
                    previous_hash=row.previous_hash,
                    record_hash=row.record_hash,
                )
                for row in rows
            ]

    @app.post(
        "/v1/incidents/{incident_id}/claim-investigation",
        dependencies=[Depends(incident_internal)],
    )
    def claim_investigation(incident_id: UUID) -> Incident:
        with sessions.begin() as session:
            record = find_incident(session, incident_id, lock=True)
            incident = Incident.model_validate(record.document)
            reclaimable = (
                incident.status == IncidentStatus.INVESTIGATING
                and incident.investigation_lease_expires_at is not None
                and incident.investigation_lease_expires_at <= datetime.now(UTC)
            )
            if (
                incident.status not in {IncidentStatus.OPEN, IncidentStatus.INVESTIGATION_FAILED}
                and not reclaimable
            ):
                raise HTTPException(409, "investigation_already_claimed")
            incident.status = IncidentStatus.INVESTIGATING
            incident.investigation_started_at = datetime.now(UTC)
            incident.investigation_completed_at = None
            incident.investigation_error = None
            incident.last_failure_at = None
            incident.investigation_attempts += 1
            incident.investigation_lease_expires_at = datetime.now(UTC) + timedelta(
                seconds=config.investigation_lease_seconds
            )
            record.document = incident.model_dump(mode="json")
            return incident

    @app.post(
        "/v1/incidents/{incident_id}/decision",
        dependencies=[Depends(incident_internal)],
    )
    def record_decision(incident_id: UUID, body: ApprovalDecisionCommand) -> Incident:
        with sessions.begin() as session:
            record = find_incident(session, incident_id, lock=True)
            incident = Incident.model_validate(record.document)
            if any(item.request_id == body.request_id for item in incident.approvals):
                previous = next(
                    item for item in incident.approvals if item.request_id == body.request_id
                )
                if (
                    previous.proposal_id == body.proposal_id
                    and previous.proposal_hash == body.proposal_hash
                    and previous.proposal_version == body.proposal_version
                    and previous.decision == body.decision
                ):
                    return incident
                raise HTTPException(409, "approval_request_replay_conflict")
            if incident.status != IncidentStatus.PROPOSAL_READY:
                raise HTTPException(409, "incident_not_ready_for_decision")
            proposal = next(
                (
                    item
                    for item in incident.remediation_proposals
                    if item.proposal_id == body.proposal_id
                ),
                None,
            )
            if proposal is None or proposal.incident_id != incident_id:
                raise HTTPException(404, "proposal_not_found")
            if proposal.status != ProposalStatus.PROPOSED:
                raise HTTPException(409, "proposal_already_decided")
            if (
                proposal.version != body.proposal_version
                or proposal.proposal_hash != body.proposal_hash
                or proposal_hash(proposal) != body.proposal_hash
            ):
                raise HTTPException(409, "stale_or_invalid_proposal")
            approval = ApprovalRecord(
                proposal_id=proposal.proposal_id,
                incident_id=incident_id,
                proposal_version=proposal.version,
                proposal_hash=proposal.proposal_hash,
                approver_identity=body.approver_identity,
                decision=body.decision,
                request_id=body.request_id,
            )
            incident.approvals.append(approval)
            proposal.status = (
                ProposalStatus.APPROVED if body.decision == "approved" else ProposalStatus.REJECTED
            )
            if body.decision == "approved":
                incident.status = IncidentStatus.APPROVED
            record.document = incident.model_dump(mode="json")
            return incident

    def audit_records(session: Session, incident_id: UUID) -> list[AuditRecord]:
        rows = session.scalars(
            select(AuditRecordRow)
            .where(AuditRecordRow.incident_id == incident_id)
            .order_by(AuditRecordRow.sequence)
        )
        return [
            AuditRecord(
                audit_id=row.id,
                chain_version=row.chain_version,
                canonicalization_version=row.canonicalization_version,
                sequence=row.sequence,
                timestamp=row.timestamp,
                event_type=row.event_type,
                incident_id=row.incident_id,
                actor=row.actor,
                metadata=row.event_metadata,
                previous_hash=row.previous_hash,
                record_hash=row.record_hash,
            )
            for row in rows
        ]

    @app.get(
        "/v1/incidents/{incident_id}/audit/verify",
        dependencies=[Depends(incident_internal)],
    )
    def verify_incident_audit(incident_id: UUID) -> ChainVerification:
        with sessions() as session:
            find_incident(session, incident_id)
            return verify_chain_report(audit_records(session, incident_id))

    @app.get("/v1/audit/verify", dependencies=[Depends(incident_internal)])
    def verify_all_audits() -> dict[str, ChainVerification]:
        with sessions() as session:
            incident_ids = session.scalars(
                select(IncidentRecord.id).order_by(IncidentRecord.id)
            ).all()
            return {
                str(incident_id): verify_chain_report(audit_records(session, incident_id))
                for incident_id in incident_ids
            }

    @app.post(
        "/v1/incidents/{incident_id}/audit/checkpoints",
        status_code=201,
        dependencies=[Depends(incident_internal)],
    )
    def checkpoint_audit(incident_id: UUID) -> AuditCheckpoint:
        with sessions.begin() as session:
            find_incident(session, incident_id, lock=True)
            checkpoint = create_checkpoint(
                audit_records(session, incident_id), config.audit_signing_secret.get_secret_value()
            )
            session.add(
                AuditCheckpointRow(
                    incident_id=incident_id,
                    checkpoint_version=checkpoint.checkpoint_version,
                    last_sequence=checkpoint.last_sequence,
                    last_record_hash=checkpoint.last_record_hash,
                    checkpoint_timestamp=checkpoint.checkpoint_timestamp,
                    signature=checkpoint.signature,
                )
            )
            return checkpoint

    @app.get(
        "/v1/incidents/{incident_id}/audit/checkpoints/latest",
        dependencies=[Depends(incident_internal)],
    )
    def latest_checkpoint(incident_id: UUID) -> AuditCheckpoint:
        with sessions() as session:
            row = session.scalar(
                select(AuditCheckpointRow)
                .where(AuditCheckpointRow.incident_id == incident_id)
                .order_by(AuditCheckpointRow.checkpoint_timestamp.desc())
                .limit(1)
            )
            if row is None:
                raise HTTPException(404, "audit_checkpoint_not_found")
            return AuditCheckpoint(
                checkpoint_version=row.checkpoint_version,
                incident_id=row.incident_id,
                last_sequence=row.last_sequence,
                last_record_hash=row.last_record_hash,
                checkpoint_timestamp=row.checkpoint_timestamp,
                signature=row.signature,
            )

    @app.get(
        "/v1/incidents/{incident_id}/audit/checkpoints/verify",
        dependencies=[Depends(incident_internal)],
    )
    def verify_latest_checkpoint(incident_id: UUID) -> dict[str, bool]:
        checkpoint = latest_checkpoint(incident_id)
        with sessions() as session:
            records = audit_records(session, incident_id)[: checkpoint.last_sequence]
        return {
            "valid": verify_checkpoint(
                checkpoint, records, config.audit_signing_secret.get_secret_value()
            )
        }

    def build_memory(incident: Incident) -> IncidentMemory:
        if (
            incident.status
            not in {IncidentStatus.PROPOSAL_READY, IncidentStatus.APPROVED, IncidentStatus.CLOSED}
            or incident.diagnosis is None
            or not incident.diagnosis.supporting_evidence_ids
            or not incident.remediation_proposals
        ):
            raise HTTPException(409, "incident_is_not_memory_eligible")
        categories = tuple(
            sorted(
                {
                    str(value.get("provenance", {}).get("source_type", "unknown"))
                    for value in incident.evidence.values()
                    if isinstance(value, dict)
                }
            )
        )
        if not categories:
            raise HTTPException(409, "incident_has_no_memory_evidence")
        proposal = incident.remediation_proposals[0]
        return IncidentMemory(
            incident_id=incident.incident_id,
            affected_service=incident.diagnosis.affected_service,
            failure_class=incident.diagnosis.failure_class,
            root_cause_summary=incident.diagnosis.concise_explanation,
            investigation_summary=incident.diagnosis.investigation_summary,
            remediation_proposal_summary=proposal.description,
            evidence_categories=categories,
            confidence=incident.diagnosis.confidence,
            tags=(incident.severity, incident.source),
        )

    @app.post(
        "/v1/incidents/{incident_id}/memory",
        status_code=201,
        dependencies=[Depends(incident_internal)],
    )
    def create_memory(incident_id: UUID) -> IncidentMemory:
        with sessions.begin() as session:
            incident = Incident.model_validate(
                find_incident(session, incident_id, lock=True).document
            )
            memory = build_memory(incident)
            if session.scalar(
                select(IncidentMemoryRow).where(IncidentMemoryRow.incident_id == incident_id)
            ):
                raise HTTPException(409, "incident_memory_already_exists")
            session.add(
                IncidentMemoryRow(
                    id=memory.memory_id,
                    incident_id=incident_id,
                    document=memory.model_dump(mode="json"),
                )
            )
            return memory

    @app.get("/v1/memory", dependencies=[Depends(incident_internal)])
    def search_memory(
        affected_service: str | None = Query(default=None, max_length=63),
        failure_class: str | None = Query(default=None, max_length=100),
        limit: int = Query(default=5, ge=1, le=10),
    ) -> list[MemorySearchResult]:
        query = MemoryQuery(
            affected_service=affected_service, failure_class=failure_class, limit=limit
        )
        with sessions() as session:
            items = [
                IncidentMemory.model_validate(row.document)
                for row in session.scalars(select(IncidentMemoryRow)).all()
            ]
        return rank_memory(items, query)

    @app.post("/v1/manual-benchmarks", status_code=201, dependencies=[Depends(incident_internal)])
    def create_manual_run(body: ManualBenchmarkRun) -> ManualBenchmarkRun:
        with sessions.begin() as session:
            session.add(
                ManualBenchmarkRow(id=body.manual_run_id, document=body.model_dump(mode="json"))
            )
        return body

    @app.get("/v1/manual-benchmarks/{run_id}", dependencies=[Depends(incident_internal)])
    def get_manual_run(run_id: UUID) -> ManualBenchmarkRun:
        with sessions() as session:
            row = session.get(ManualBenchmarkRow, run_id)
            if row is None:
                raise HTTPException(404, "manual_run_not_found")
            return ManualBenchmarkRun.model_validate(row.document)

    @app.put("/v1/manual-benchmarks/{run_id}", dependencies=[Depends(incident_internal)])
    def finalize_manual_run(run_id: UUID, body: ManualBenchmarkRun) -> ManualBenchmarkRun:
        if run_id != body.manual_run_id or not body.finalized:
            raise HTTPException(422, "manual_run_identity_or_finalization_invalid")
        with sessions.begin() as session:
            row = session.get(ManualBenchmarkRow, run_id, with_for_update=True)
            if row is None:
                raise HTTPException(404, "manual_run_not_found")
            if row.finalized:
                raise HTTPException(409, "manual_run_already_finalized")
            row.document, row.finalized = body.model_dump(mode="json"), True
        return body

    @app.post("/v1/evaluation-runs", status_code=201, dependencies=[Depends(incident_internal)])
    def create_evaluation_run(body: EvaluationRun) -> EvaluationRun:
        with sessions.begin() as session:
            session.add(
                EvaluationRunRow(id=body.evaluation_run_id, document=body.model_dump(mode="json"))
            )
        return body

    @app.get("/v1/evaluation-runs/{run_id}", dependencies=[Depends(incident_internal)])
    def get_evaluation_run(run_id: UUID) -> EvaluationRun:
        with sessions() as session:
            row = session.get(EvaluationRunRow, run_id)
            if row is None:
                raise HTTPException(404, "evaluation_run_not_found")
            return EvaluationRun.model_validate(row.document)

    return app
