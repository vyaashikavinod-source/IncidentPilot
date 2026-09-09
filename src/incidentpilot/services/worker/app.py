"""Celery entrypoint: celery -A incidentpilot.services.worker.app:app worker."""

from __future__ import annotations

import time
from uuid import UUID

from celery import Task
from prometheus_client import start_http_server

from incidentpilot.services.worker.processing import process_job, record_failure
from incidentpilot.services.worker.queue import TASK_NAME, create_queue
from incidentpilot.shared.clients import DataClient, UpstreamError
from incidentpilot.shared.config import WorkerSettings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics
from incidentpilot.shared.request_id import normalize_request_id
from incidentpilot.shared.telemetry import configure_telemetry

settings = WorkerSettings()
app = create_queue(settings.broker_url.get_secret_value())
metrics = Metrics(settings.service_name)
telemetry = configure_telemetry(settings, instrument_celery=True)
configure_logging(settings)
if settings.telemetry_enabled:
    start_http_server(9100, registry=metrics.registry)


@app.task(bind=True, name=TASK_NAME, max_retries=settings.worker_retry_limit)
def run_job(self: Task[[str, str], None], job_id: str, correlation_id: str) -> None:
    started = time.monotonic()
    token = request_id.set(normalize_request_id(correlation_id))
    client = DataClient(
        settings.data_url, settings.http_timeout, settings.internal_token.get_secret_value()
    )
    metrics.tasks.labels(settings.service_name, "started").inc()
    try:
        identifier = UUID(job_id)
        try:
            process_job(client, identifier)
            metrics.tasks.labels(settings.service_name, "completed").inc()
            metrics.jobs.labels(settings.service_name, "completed").inc()
        except UpstreamError as exc:
            if exc.retryable and self.request.retries < settings.worker_retry_limit:
                metrics.tasks.labels(settings.service_name, "retry").inc()
                raise self.retry(exc=exc, countdown=settings.worker_retry_delay) from exc
            record_failure(client, identifier)
            metrics.tasks.labels(settings.service_name, "failed").inc()
            metrics.jobs.labels(settings.service_name, "failed").inc()
            raise
        except Exception:
            record_failure(client, identifier)
            metrics.tasks.labels(settings.service_name, "failed").inc()
            metrics.jobs.labels(settings.service_name, "failed").inc()
            raise
    finally:
        metrics.task_duration.labels(settings.service_name).observe(time.monotonic() - started)
        client.close()
        request_id.reset(token)
