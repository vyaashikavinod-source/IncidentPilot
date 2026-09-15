import os
from uuid import UUID

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.agent_integration]


def test_live_incident_persistence_and_investigation_gate() -> None:
    if os.getenv("INCIDENTPILOT_RUN_AGENT_INTEGRATION") != "1":
        pytest.skip("set INCIDENTPILOT_RUN_AGENT_INTEGRATION=1 for the live agent service")
    token = os.environ["INCIDENTPILOT_INTERNAL_TOKEN"]
    provider = os.getenv("INCIDENTPILOT_LLM_PROVIDER", "fake")
    client = httpx.Client(
        base_url=os.getenv("INCIDENTPILOT_AGENT_URL", "http://127.0.0.1:8002"),
        headers={"X-Internal-Token": token},
        timeout=120,
    )
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
    investigated = client.post(f"/v1/incidents/{incident_id}/investigate")
    if provider == "fake":
        assert investigated.status_code == 503
        assert investigated.json()["detail"] == "real_llm_provider_not_configured"
        return
    assert investigated.status_code == 200
    body = investigated.json()
    assert body["diagnosis"]["supporting_evidence_ids"]
    assert body["remediation_proposals"][0]["status"] == "proposed"
    assert client.get(f"/v1/incidents/{incident_id}/audit/verify").json()["valid"]
