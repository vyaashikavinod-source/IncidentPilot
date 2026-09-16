import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from incidentpilot.security.auth import OperatorIdentity, Role, issue_token

pytestmark = [pytest.mark.integration, pytest.mark.agent_integration]


def test_live_incident_persistence_and_investigation_gate() -> None:
    if os.getenv("INCIDENTPILOT_RUN_AGENT_INTEGRATION") != "1":
        pytest.skip("set INCIDENTPILOT_RUN_AGENT_INTEGRATION=1 for the live agent service")
    signing_secret = os.environ["INCIDENTPILOT_OPERATOR_SIGNING_SECRET"]
    provider = os.getenv("INCIDENTPILOT_LLM_PROVIDER", "fake")

    def token(role: Role) -> str:
        return issue_token(
            OperatorIdentity(
                subject=f"live-{role.value}@example.test",
                roles=frozenset({role}),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                token_id=f"live-{role.value}-token",
                issuer="incidentpilot-local",
                audience="incidentpilot-operator-api",
            ),
            signing_secret,
        )

    base_url = os.getenv("INCIDENTPILOT_AGENT_URL", "http://127.0.0.1:8002")
    assert httpx.get(f"{base_url}/v1/incidents/{UUID(int=0)}").status_code == 401
    investigator_headers = {"Authorization": f"Bearer {token(Role.INVESTIGATOR)}"}
    client = httpx.Client(base_url=base_url, headers=investigator_headers, timeout=120)
    created = client.post(
        "/v1/incidents",
        json={
            "source": "integration-test",
            "title": "Observed sandbox degradation",
            "description": "Investigate the monitored services using read-only evidence.",
            "severity": "medium",
            "alert_metadata": {"test": "live-persistence"},
        },
    )
    assert created.status_code == 201
    incident_id = UUID(created.json()["incident_id"])
    persisted = client.get(f"/v1/incidents/{incident_id}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "open"
    viewer_headers = {"Authorization": f"Bearer {token(Role.VIEWER)}"}
    assert (
        client.post(f"/v1/incidents/{incident_id}/investigate", headers=viewer_headers).status_code
        == 403
    )
    investigated = client.post(
        f"/v1/incidents/{incident_id}/investigate", headers=investigator_headers
    )
    if provider == "fake":
        assert investigated.status_code == 503
        assert investigated.json()["detail"] == "real_llm_provider_not_configured"
        admin_headers = {"Authorization": f"Bearer {token(Role.ADMIN)}"}
        checkpoint = client.post(
            f"/v1/incidents/{incident_id}/audit/checkpoints", headers=admin_headers
        )
        assert checkpoint.status_code == 201
        assert client.get(
            f"/v1/incidents/{incident_id}/audit/checkpoints/verify", headers=viewer_headers
        ).json()["valid"]
        assert client.get("/v1/audit/verify", headers=admin_headers).json()[str(incident_id)][
            "valid"
        ]
        assert "incidentpilot_agent_security_events_total" in client.get("/metrics").text
        return
    assert investigated.status_code == 200
    body = investigated.json()
    assert body["diagnosis"]["supporting_evidence_ids"]
    assert body["remediation_proposals"][0]["status"] == "proposed"
    assert client.get(
        f"/v1/incidents/{incident_id}/audit/verify", headers=investigator_headers
    ).json()["valid"]
