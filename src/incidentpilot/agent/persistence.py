from uuid import UUID

import httpx
from pydantic import ValidationError

from incidentpilot.incidents.audit import AuditAppend, AuditRecord
from incidentpilot.incidents.models import Incident


class IncidentStoreError(RuntimeError):
    pass


class IncidentStore:
    def __init__(
        self,
        data_url: str,
        token: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ):
        self.http = httpx.Client(base_url=data_url, timeout=timeout, transport=transport)
        self.headers = {"X-Internal-Token": token}

    def close(self) -> None:
        self.http.close()

    def _decode(self, response: httpx.Response, model: type[Incident]) -> Incident:
        try:
            response.raise_for_status()
            return model.model_validate(response.json())
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

    def update(self, incident: Incident) -> Incident:
        return self._decode(
            self.http.put(
                f"/v1/incidents/{incident.incident_id}",
                headers=self.headers,
                json=incident.model_dump(mode="json"),
            ),
            Incident,
        )

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
