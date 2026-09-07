"""Synchronous typed clients; FastAPI routes run blocking I/O in its threadpool."""

from typing import TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.schemas import Identity, Job, JobCreate, JobPatch

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class UpstreamError(Exception):
    def __init__(self, kind: str, status: int | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in {429, 502, 503, 504} or self.status == 500


class ServiceClient:
    def __init__(
        self, url: str, timeout: float, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.http = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: BaseModel | None = None,
    ) -> httpx.Response:
        try:
            response = self.http.request(
                method,
                path,
                headers={**(headers or {}), "X-Request-ID": request_id.get()},
                json=body.model_dump(mode="json") if body else None,
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise UpstreamError("upstream_timeout") from exc
        except httpx.RequestError as exc:
            raise UpstreamError("upstream_connection_failure") from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamError("upstream_http_failure", exc.response.status_code) from exc

    def decode(self, response: httpx.Response, model: type[ResponseModel]) -> ResponseModel:
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError("upstream_malformed_response", 502) from exc

    def ready(self) -> None:
        response = self.request("GET", "/ready")
        try:
            if response.json() == {"status": "ready"}:
                return
        except ValueError as exc:
            raise UpstreamError("upstream_malformed_readiness", 502) from exc
        raise UpstreamError("upstream_not_ready", 503)


class AuthClient(ServiceClient):
    def validate(self, authorization: str) -> Identity:
        identity = self.decode(
            self.request("POST", "/v1/auth/validate", {"Authorization": authorization}), Identity
        )
        if not identity.authenticated:
            raise UpstreamError("authentication_rejected", 401)
        return identity


class DataClient(ServiceClient):
    def __init__(
        self,
        url: str,
        timeout: float,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(url, timeout, transport)
        self.headers = {"X-Internal-Token": token}

    def create(self, body: JobCreate) -> Job:
        return self.decode(self.request("POST", "/v1/jobs", self.headers, body), Job)

    def get(self, job_id: UUID) -> Job:
        return self.decode(self.request("GET", f"/v1/jobs/{job_id}", self.headers), Job)

    def patch(self, job_id: UUID, body: JobPatch) -> Job:
        return self.decode(self.request("PATCH", f"/v1/jobs/{job_id}", self.headers, body), Job)
