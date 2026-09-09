"""Bounded-cardinality Prometheus metrics for HTTP, dependencies, jobs and workers."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self, service: str) -> None:
        self.registry = CollectorRegistry()
        labels = ["service", "method", "route", "status_class"]
        self.http_requests = Counter(
            "incidentpilot_http_requests_total", "HTTP responses", labels, registry=self.registry
        )
        self.http_duration = Histogram(
            "incidentpilot_http_request_duration_seconds",
            "HTTP request duration",
            ["service", "method", "route"],
            registry=self.registry,
        )
        self.http_active = Gauge(
            "incidentpilot_http_requests_active",
            "In-flight HTTP requests",
            ["service"],
            registry=self.registry,
        )
        self.dependency_requests = Counter(
            "incidentpilot_dependency_requests_total",
            "Dependency requests",
            ["service", "dependency", "outcome"],
            registry=self.registry,
        )
        self.dependency_duration = Histogram(
            "incidentpilot_dependency_request_duration_seconds",
            "Dependency request duration",
            ["service", "dependency"],
            registry=self.registry,
        )
        self.readiness = Gauge(
            "incidentpilot_readiness", "Last readiness state", ["service"], registry=self.registry
        )
        self.jobs = Counter(
            "incidentpilot_jobs_total",
            "Job lifecycle events",
            ["service", "event"],
            registry=self.registry,
        )
        self.tasks = Counter(
            "incidentpilot_worker_tasks_total",
            "Worker task outcomes",
            ["service", "outcome"],
            registry=self.registry,
        )
        self.task_duration = Histogram(
            "incidentpilot_worker_task_duration_seconds",
            "Worker task duration",
            ["service"],
            registry=self.registry,
        )
        self.queue_depth = Gauge(
            "incidentpilot_queue_depth",
            "Observed Celery jobs queue depth",
            ["service", "queue"],
            registry=self.registry,
        )
        self.database = Histogram(
            "incidentpilot_database_operation_duration_seconds",
            "Database operation duration",
            ["service", "operation"],
            registry=self.registry,
        )
        self.service = service

    def install(self, app: FastAPI) -> None:
        from prometheus_client import generate_latest

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            return PlainTextResponse(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)

        @app.middleware("http")
        async def observe(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            self.http_active.labels(self.service).inc()
            started = time.monotonic()
            try:
                response = await call_next(request)
                return response
            finally:
                route = request.scope.get("route")
                template = getattr(route, "path", "unmatched")
                status = response.status_code if "response" in locals() else 500
                self.http_requests.labels(
                    self.service, request.method, template, f"{status // 100}xx"
                ).inc()
                self.http_duration.labels(self.service, request.method, template).observe(
                    time.monotonic() - started
                )
                self.http_active.labels(self.service).dec()
