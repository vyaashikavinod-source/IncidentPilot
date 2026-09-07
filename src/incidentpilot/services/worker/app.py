"""Celery entrypoint: celery -A incidentpilot.services.worker.app:app worker."""

from __future__ import annotations

from uuid import UUID

from celery import Task

from incidentpilot.services.worker.processing import process_job, record_failure
from incidentpilot.services.worker.queue import TASK_NAME, create_queue
from incidentpilot.shared.clients import DataClient, UpstreamError
from incidentpilot.shared.config import WorkerSettings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.request_id import normalize_request_id

settings = WorkerSettings()
app = create_queue(settings.broker_url.get_secret_value())
configure_logging(settings)


@app.task(bind=True, name=TASK_NAME, max_retries=settings.worker_retry_limit)
def run_job(self: Task[[str, str], None], job_id: str, correlation_id: str) -> None:
    token = request_id.set(normalize_request_id(correlation_id))
    client = DataClient(
        settings.data_url, settings.http_timeout, settings.internal_token.get_secret_value()
    )
    try:
        identifier = UUID(job_id)
        try:
            process_job(client, identifier)
        except UpstreamError as exc:
            if exc.retryable and self.request.retries < settings.worker_retry_limit:
                raise self.retry(exc=exc, countdown=settings.worker_retry_delay) from exc
            record_failure(client, identifier)
            raise
        except Exception:
            record_failure(client, identifier)
            raise
    finally:
        client.close()
        request_id.reset(token)
