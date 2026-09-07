"""Correlation only; no distributed tracing."""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from incidentpilot.shared.correlation import request_id


def normalize_request_id(value: str | None) -> str:
    try:
        return str(UUID(value)) if value else str(uuid4())
    except ValueError:
        return str(uuid4())


def install_request_ids(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        value = normalize_request_id(request.headers.get("X-Request-ID"))
        token = request_id.set(value)
        try:
            try:
                response = await call_next(request)
            except Exception:
                logging.getLogger("incidentpilot.http").exception("http_request_failed")
                response = JSONResponse(
                    status_code=500, content={"detail": "internal_server_error"}
                )
            response.headers["X-Request-ID"] = value
            return response
        finally:
            status = response.status_code if "response" in locals() else 500
            logging.getLogger("incidentpilot.http").info(
                "http_request_finished", extra={"http_status": status}
            )
            request_id.reset(token)
