"""Single sandbox identity. This is deliberately not production authentication."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException

from incidentpilot.shared.config import AuthSettings
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics
from incidentpilot.shared.schemas import Identity
from incidentpilot.shared.telemetry import configure_telemetry


def create_app(settings: AuthSettings | None = None) -> FastAPI:
    config = settings or AuthSettings()
    metrics = Metrics(config.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config)
        try:
            yield
        finally:
            telemetry.shutdown()

    app = FastAPI(title="IncidentPilot sandbox auth", lifespan=lifespan)
    telemetry = configure_telemetry(config, app)
    configure_http(app)
    metrics.install(app)

    @app.get("/ready")
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/v1/auth/validate")
    def validate(authorization: Annotated[str | None, Header()] = None) -> Identity:
        scheme, _, credential = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            credential.encode(), config.sandbox_auth_token.get_secret_value().encode()
        ):
            raise HTTPException(
                401, "invalid sandbox credential", headers={"WWW-Authenticate": "Bearer"}
            )
        return Identity(subject="sandbox-user", roles=["sandbox_user"], authenticated=True)

    return app
