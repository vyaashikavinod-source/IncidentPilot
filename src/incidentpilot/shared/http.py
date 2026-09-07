"""Common HTTP error boundaries; never expose exception bodies or credentials."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from incidentpilot.shared.clients import UpstreamError
from incidentpilot.shared.request_id import install_request_ids


def configure_http(app: FastAPI) -> None:
    install_request_ids(app)

    @app.exception_handler(UpstreamError)
    async def upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
        logging.getLogger("incidentpilot.http").warning(exc.kind)
        status = exc.status if exc.status in {401, 403, 404, 409} else 503
        return JSONResponse(status_code=status, content={"detail": exc.kind})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "alive"}
