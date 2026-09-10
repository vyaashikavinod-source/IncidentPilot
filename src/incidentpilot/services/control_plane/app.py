"""Read-only operational evidence API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from incidentpilot.services.control_plane.sources import (
    SERVICES,
    DeploymentSource,
    EvidenceBackendError,
    LokiSource,
    PrometheusSource,
    ServiceStatusSource,
    TempoSource,
)
from incidentpilot.shared.config import ControlPlaneSettings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.evidence import (
    DeploymentEvidence,
    LogsEvidence,
    MetricsEvidence,
    ServiceStatusEvidence,
    TraceEvidence,
)
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.telemetry import configure_telemetry


def create_app(settings: ControlPlaneSettings | None = None) -> FastAPI:
    config = settings or ControlPlaneSettings()
    prometheus = PrometheusSource(config.prometheus_url, config.http_timeout)
    loki = LokiSource(config.loki_url, config.http_timeout)
    tempo = TempoSource(config.tempo_url, config.http_timeout)
    statuses = ServiceStatusSource(
        {
            "gateway": config.gateway_url,
            "auth": config.auth_url,
            "data": config.data_url,
            "worker": config.worker_metrics_url,
        },
        config.http_timeout,
    )
    deployments = DeploymentSource(
        config.data_url, config.http_timeout, config.internal_token.get_secret_value()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config)
        try:
            yield
        finally:
            telemetry.shutdown()

    app = FastAPI(title="IncidentPilot read-only evidence plane", lifespan=lifespan)
    telemetry = configure_telemetry(config, app)
    configure_http(app)

    def current_request_id() -> UUID:
        return UUID(request_id.get())

    @app.exception_handler(EvidenceBackendError)
    async def backend_error(request: Request, exc: EvidenceBackendError) -> JSONResponse:
        logging.getLogger("incidentpilot.evidence").warning(
            "evidence_backend_unavailable", extra={"backend_error": str(exc)}
        )
        return JSONResponse(status_code=503, content={"detail": "evidence_backend_unavailable"})

    @app.get("/ready")
    def ready() -> dict[str, object]:
        sources = {
            "prometheus": f"{config.prometheus_url}/-/ready",
            "loki": f"{config.loki_url}/ready",
            "tempo": f"{config.tempo_url}/ready",
            "service_health": f"{config.gateway_url}/health",
            "deployment_history": f"{config.data_url}/ready",
        }
        state: dict[str, bool] = {}
        for name, url in sources.items():
            try:
                state[name] = httpx.get(url, timeout=config.http_timeout).status_code == 200
            except httpx.HTTPError:
                state[name] = False
        return {"status": "ready" if all(state.values()) else "degraded", "sources": state}

    @app.get("/v1/evidence/services", response_model=ServiceStatusEvidence)
    def services() -> ServiceStatusEvidence:
        return statuses.get(current_request_id())

    @app.get("/v1/evidence/deployments", response_model=DeploymentEvidence)
    def deployment_history(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> DeploymentEvidence:
        return deployments.get(limit, current_request_id())

    @app.get("/v1/evidence/metrics/{kind}", response_model=MetricsEvidence)
    def metrics(
        kind: Annotated[Literal["requests", "jobs", "dependencies", "readiness"], Path()],
        service: Annotated[str | None, Query()] = None,
        window_seconds: Annotated[int, Query(ge=60)] = 900,
    ) -> MetricsEvidence:
        if window_seconds > config.evidence_max_window_seconds:
            raise HTTPException(422, "query window exceeds configured maximum")
        if service is not None and service not in SERVICES:
            raise HTTPException(422, "unsupported service")
        return prometheus.query(kind, service, window_seconds, current_request_id())

    @app.get("/v1/evidence/logs", response_model=LogsEvidence)
    def logs(
        service: Annotated[str, Query()],
        environment: Annotated[str, Query()] = "local",
        level: Annotated[str | None, Query()] = None,
        request_id_filter: Annotated[str | None, Query(alias="request_id")] = None,
        trace_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")] = None,
        start: Annotated[datetime | None, Query()] = None,
        end: Annotated[datetime | None, Query()] = None,
        limit: Annotated[int, Query(ge=1)] = 100,
    ) -> LogsEvidence:
        now = datetime.now(UTC)
        finish = end or now
        begin = start or finish - timedelta(minutes=15)
        if begin.tzinfo is None or finish.tzinfo is None or begin >= finish:
            raise HTTPException(422, "invalid UTC time range")
        if (finish - begin).total_seconds() > config.evidence_max_window_seconds:
            raise HTTPException(422, "query window exceeds configured maximum")
        if limit > config.evidence_max_results:
            raise HTTPException(422, "result limit exceeds configured maximum")
        return loki.query(
            service,
            environment,
            level,
            request_id_filter,
            trace_id,
            begin,
            finish,
            limit,
            current_request_id(),
        )

    @app.get("/v1/evidence/traces/{trace_id}", response_model=TraceEvidence)
    def trace(trace_id: str) -> TraceEvidence:
        try:
            return tempo.get(trace_id, current_request_id())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app
