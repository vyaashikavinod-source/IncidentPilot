import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Response
from redis import Redis
from redis.exceptions import RedisError

from incidentpilot.services.worker.queue import TASK_NAME, create_queue
from incidentpilot.shared.clients import AuthClient, DataClient, UpstreamError
from incidentpilot.shared.config import GatewaySettings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics
from incidentpilot.shared.schemas import Job, JobInput, JobPatch, JobStatus, JobSubmissionCreate
from incidentpilot.shared.telemetry import configure_telemetry


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    config = settings or GatewaySettings()
    metrics = Metrics(config.service_name)
    auth = AuthClient(config.auth_url, config.http_timeout, metrics=metrics)
    data = DataClient(
        config.data_url,
        config.http_timeout,
        config.internal_token.get_secret_value(),
        metrics=metrics,
    )
    queue = create_queue(config.broker_url.get_secret_value())
    broker = Redis.from_url(
        config.broker_url.get_secret_value(), socket_connect_timeout=3, socket_timeout=3
    )
    queue_depth = metrics.queue_depth.labels(config.service_name, "jobs")

    def observe_queue_depth() -> float:
        try:
            return float(cast(int, broker.llen("jobs")))
        except RedisError:
            return float("nan")

    queue_depth.set_function(observe_queue_depth)
    logger = logging.getLogger("incidentpilot.gateway")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config)
        try:
            yield
        finally:
            auth.close()
            data.close()
            broker.close()
            queue.close()
            telemetry.shutdown()

    app = FastAPI(title="IncidentPilot gateway", lifespan=lifespan)
    telemetry = configure_telemetry(config, app, instrument_celery=True)
    configure_http(app)
    metrics.install(app)
    # Explicit handles also allow isolated transport tests; no fallback implementation.
    app.state.auth, app.state.data, app.state.queue, app.state.broker = auth, data, queue, broker

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            auth.ready()
            data.ready()
            broker.ping()
        except RedisError as exc:
            metrics.readiness.labels(config.service_name).set(0)
            raise HTTPException(503, "broker_unavailable") from exc
        except UpstreamError:
            metrics.readiness.labels(config.service_name).set(0)
            raise
        metrics.readiness.labels(config.service_name).set(1)
        return {"status": "ready"}

    def authenticate(authorization: str | None) -> str:
        if not authorization:
            raise HTTPException(
                401, "Authorization required", headers={"WWW-Authenticate": "Bearer"}
            )
        return auth.validate(authorization).subject

    @app.post("/v1/jobs", status_code=202)
    def create(
        body: JobInput,
        response: Response,
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key: Annotated[
            str | None,
            Header(
                alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
            ),
        ] = None,
    ) -> Job:
        owner = authenticate(authorization)
        if idempotency_key is None:
            raise HTTPException(400, "Idempotency-Key required")
        digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        submission = data.create(
            JobSubmissionCreate(
                description=body.description,
                owner_id=owner,
                idempotency_key=idempotency_key,
                payload_sha256=digest,
            )
        )
        job = submission.job
        response.headers["Idempotency-Replayed"] = str(submission.replayed).lower()
        if submission.replayed:
            metrics.jobs.labels(config.service_name, "replayed").inc()
            return job
        try:
            queue.send_task(TASK_NAME, args=[str(job.id), request_id.get()], retry=False)
        except Exception as exc:
            metrics.jobs.labels(config.service_name, "enqueue_failed").inc()
            # Publish acknowledgement is ambiguous: do not claim a queued submission succeeded.
            logger.error("job_enqueue_failed")
            try:
                data.patch(job.id, JobPatch(status=JobStatus.FAILED, error="enqueue_failed"))
            except UpstreamError:
                logger.error("enqueue_failure_could_not_be_recorded")
            raise HTTPException(503, {"code": "enqueue_failed", "job_id": str(job.id)}) from exc
        logger.info("job_enqueued")
        metrics.jobs.labels(config.service_name, "submitted").inc()
        return job

    @app.get("/v1/jobs/{job_id}")
    def get(job_id: UUID, authorization: Annotated[str | None, Header()] = None) -> Job:
        owner = authenticate(authorization)
        job = data.get(job_id)
        if job.owner_id != owner:
            raise HTTPException(404, "job_not_found")
        return job

    return app
