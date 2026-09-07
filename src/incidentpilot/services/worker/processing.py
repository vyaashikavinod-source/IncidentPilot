"""Deterministic work; repeated delivery has no external side effects."""

import hashlib
import logging
from uuid import UUID

from incidentpilot.shared.clients import DataClient, UpstreamError
from incidentpilot.shared.schemas import JobPatch, JobResult, JobStatus

logger = logging.getLogger("incidentpilot.worker")


def process_job(client: DataClient, job_id: UUID) -> None:
    job = client.get(job_id)
    if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
        logger.info("job_already_terminal")
        return
    try:
        client.patch(job_id, JobPatch(status=JobStatus.RUNNING))
    except UpstreamError as exc:
        if exc.status != 409:
            raise
        # A concurrent duplicate may have completed after our initial GET.
        refreshed = client.get(job_id)
        if refreshed.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            logger.info("job_already_terminal")
            return
        raise
    logger.info("job_running")
    result = JobResult(
        word_count=len(job.description.split()),
        character_count=len(job.description),
        sha256=hashlib.sha256(job.description.encode()).hexdigest(),
    )
    client.patch(job_id, JobPatch(status=JobStatus.COMPLETED, result=result))
    logger.info("job_completed")


def record_failure(client: DataClient, job_id: UUID) -> None:
    try:
        client.patch(job_id, JobPatch(status=JobStatus.FAILED, error="worker_processing_failed"))
    except UpstreamError:
        logger.error("job_failure_could_not_be_recorded")
