import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException
from redis import Redis
from redis.exceptions import RedisError

from incidentpilot.services.worker.queue import TASK_NAME, create_queue
from incidentpilot.shared.clients import AuthClient, DataClient, UpstreamError
from incidentpilot.shared.config import GatewaySettings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.schemas import Job, JobCreate, JobInput, JobPatch, JobStatus


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    config = settings or GatewaySettings()
    auth = AuthClient(config.auth_url, config.http_timeout)
    data = DataClient(
        config.data_url, config.http_timeout, config.internal_token.get_secret_value()
    )
    queue = create_queue(config.broker_url.get_secret_value())
    broker = Redis.from_url(
        config.broker_url.get_secret_value(), socket_connect_timeout=3, socket_timeout=3
    )
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

    app = FastAPI(title="IncidentPilot gateway", lifespan=lifespan)
    configure_http(app)
    # Explicit handles also allow isolated transport tests; no fallback implementation.
    app.state.auth, app.state.data, app.state.queue, app.state.broker = auth, data, queue, broker

    @app.get("/ready")
    def ready() -> dict[str, str]:
        auth.ready()
        data.ready()
        try:
            broker.ping()
        except RedisError as exc:
            raise HTTPException(503, "broker_unavailable") from exc
        return {"status": "ready"}

    def authenticate(authorization: str | None) -> str:
        if not authorization:
            raise HTTPException(
                401, "Authorization required", headers={"WWW-Authenticate": "Bearer"}
            )
        return auth.validate(authorization).subject

    @app.post("/v1/jobs", status_code=202)
    def create(body: JobInput, authorization: Annotated[str | None, Header()] = None) -> Job:
        owner = authenticate(authorization)
        job = data.create(JobCreate(description=body.description, owner_id=owner))
        try:
            queue.send_task(TASK_NAME, args=[str(job.id), request_id.get()], retry=False)
        except Exception as exc:
            # Publish acknowledgement is ambiguous: do not claim a queued submission succeeded.
            logger.error("job_enqueue_failed")
            try:
                data.patch(job.id, JobPatch(status=JobStatus.FAILED, error="enqueue_failed"))
            except UpstreamError:
                logger.error("enqueue_failure_could_not_be_recorded")
            raise HTTPException(503, {"code": "enqueue_failed", "job_id": str(job.id)}) from exc
        logger.info("job_enqueued")
        return job

    @app.get("/v1/jobs/{job_id}")
    def get(job_id: UUID, authorization: Annotated[str | None, Header()] = None) -> Job:
        owner = authenticate(authorization)
        job = data.get(job_id)
        if job.owner_id != owner:
            raise HTTPException(404, "job_not_found")
        return job

    return app
