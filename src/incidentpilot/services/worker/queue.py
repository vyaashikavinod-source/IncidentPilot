"""Restricted named task publishing, never arbitrary commands."""

from celery import Celery

TASK_NAME = "incidentpilot.process_job"


def create_queue(broker_url: str) -> Celery:
    app = Celery("incidentpilot", broker=broker_url)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_default_queue="jobs",
        task_publish_retry=False,
        broker_connection_timeout=3,
        broker_transport_options={
            "socket_connect_timeout": 3,
            "socket_timeout": 3,
            "visibility_timeout": 300,
        },
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=5,
        worker_prefetch_multiplier=1,
        worker_hijack_root_logger=False,
        task_acks_late=True,
        task_reject_on_worker_lost=False,
        task_soft_time_limit=60,
        task_time_limit=90,
    )
    return app
