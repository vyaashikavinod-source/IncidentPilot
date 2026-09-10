import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from incidentpilot.services.data.models import DeploymentRecord, JobRecord
from incidentpilot.shared.config import DataSettings
from incidentpilot.shared.evidence import Deployment
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics
from incidentpilot.shared.schemas import Job, JobCreate, JobPatch, transition_allowed
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
    def create(body: JobCreate) -> Job:
        with sessions.begin() as session:
            record = JobRecord(owner_id=body.owner_id, description=body.description)
            session.add(record)
            session.flush()
            return Job.model_validate(record)

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

    return app
