from uuid import UUID

import httpx
from pydantic import ValidationError

from incidentpilot.incidents.audit import (
    AuditAppend,
    AuditCheckpoint,
    AuditRecord,
    ChainVerification,
)
from incidentpilot.incidents.models import ApprovalDecisionCommand, Incident, IncidentList
from incidentpilot.memory.models import IncidentMemory, MemoryQuery, MemorySearchResult


class IncidentStoreError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class IncidentStore:
    def __init__(
        self,
        data_url: str,
        token: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ):
        self.http = httpx.Client(base_url=data_url, timeout=timeout, transport=transport)
        self.headers = {"X-Incident-Token": token}

    def close(self) -> None:
        self.http.close()

    def _decode(self, response: httpx.Response, model: type[Incident]) -> Incident:
        try:
            response.raise_for_status()
            return model.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            raise IncidentStoreError(
                "incident persistence operation failed", exc.response.status_code
            ) from exc
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise IncidentStoreError("incident persistence operation failed") from exc

    def create(self, incident: Incident) -> Incident:
        return self._decode(
            self.http.post(
                "/v1/incidents", headers=self.headers, json=incident.model_dump(mode="json")
            ),
            Incident,
        )

    def get(self, incident_id: UUID) -> Incident:
        return self._decode(
            self.http.get(f"/v1/incidents/{incident_id}", headers=self.headers), Incident
        )

    def list_incidents(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        severity: str | None = None,
        affected_service: str | None = None,
    ) -> IncidentList:
        params = {
            "limit": limit,
            "offset": offset,
            "status": status,
            "severity": severity,
            "affected_service": affected_service,
        }
        response = self.http.get(
            "/v1/incidents",
            headers=self.headers,
            params={key: value for key, value in params.items() if value is not None},
        )
        try:
            response.raise_for_status()
            return IncidentList.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise IncidentStoreError("incident listing failed") from exc

    def update(self, incident: Incident) -> Incident:
        return self._decode(
            self.http.put(
                f"/v1/incidents/{incident.incident_id}",
                headers=self.headers,
                json=incident.model_dump(mode="json"),
            ),
            Incident,
        )

    def claim(self, incident_id: UUID) -> Incident:
        response = self.http.post(
            f"/v1/incidents/{incident_id}/claim-investigation", headers=self.headers
        )
        return self._decode(response, Incident)

    def decide(self, incident_id: UUID, command: ApprovalDecisionCommand) -> Incident:
        response = self.http.post(
            f"/v1/incidents/{incident_id}/decision",
            headers=self.headers,
            json=command.model_dump(mode="json"),
        )
        return self._decode(response, Incident)

    def audit(
        self,
        incident_id: UUID,
        event_type: str,
        actor: str,
        metadata: dict[str, object] | None = None,
    ) -> AuditRecord:
        body = AuditAppend(event_type=event_type, actor=actor, metadata=metadata or {})
        response = self.http.post(
            f"/v1/incidents/{incident_id}/audit",
            headers=self.headers,
            json=body.model_dump(mode="json"),
        )
        try:
            response.raise_for_status()
            return AuditRecord.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise IncidentStoreError("audit persistence operation failed") from exc

    def audits(self, incident_id: UUID) -> list[AuditRecord]:
        response = self.http.get(f"/v1/incidents/{incident_id}/audit", headers=self.headers)
        try:
            response.raise_for_status()
            return [AuditRecord.model_validate(item) for item in response.json()]
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise IncidentStoreError("audit retrieval failed") from exc

    def verify_audit(self, incident_id: UUID) -> ChainVerification:
        response = self.http.get(f"/v1/incidents/{incident_id}/audit/verify", headers=self.headers)
        try:
            response.raise_for_status()
            return ChainVerification.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise IncidentStoreError("audit verification failed") from exc

    def verify_all_audits(self) -> dict[str, ChainVerification]:
        response = self.http.get("/v1/audit/verify", headers=self.headers)
        try:
            response.raise_for_status()
            return {
                key: ChainVerification.model_validate(value)
                for key, value in response.json().items()
            }
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise IncidentStoreError("full audit verification failed") from exc

    def checkpoint(self, incident_id: UUID) -> AuditCheckpoint:
        response = self.http.post(
            f"/v1/incidents/{incident_id}/audit/checkpoints", headers=self.headers
        )
        try:
            response.raise_for_status()
            return AuditCheckpoint.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise IncidentStoreError("audit checkpoint creation failed") from exc

    def verify_checkpoint(self, incident_id: UUID) -> bool:
        response = self.http.get(
            f"/v1/incidents/{incident_id}/audit/checkpoints/verify", headers=self.headers
        )
        try:
            response.raise_for_status()
            return bool(response.json()["valid"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise IncidentStoreError("audit checkpoint verification failed") from exc

    def create_memory(self, incident_id: UUID) -> IncidentMemory:
        response = self.http.post(f"/v1/incidents/{incident_id}/memory", headers=self.headers)
        try:
            response.raise_for_status()
            return IncidentMemory.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise IncidentStoreError("memory persistence failed") from exc

    def search_memory(self, query: MemoryQuery) -> list[MemorySearchResult]:
        response = self.http.get(
            "/v1/memory",
            headers=self.headers,
            params=query.model_dump(exclude={"tags"}, exclude_none=True),
        )
        try:
            response.raise_for_status()
            return [MemorySearchResult.model_validate(item) for item in response.json()]
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise IncidentStoreError("memory retrieval failed") from exc
