import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException

from incidentpilot.agent.engine import InvestigationEngine, InvestigationError
from incidentpilot.agent.metrics import AgentMetrics
from incidentpilot.agent.persistence import IncidentStore
from incidentpilot.agent.provider import FakeProvider, LLMProvider, OpenAIProvider, ProviderError
from incidentpilot.agent.tools import EvidenceTools
from incidentpilot.incidents.approval import proposal_hash
from incidentpilot.incidents.audit import verify_chain
from incidentpilot.incidents.models import (
    ApprovalRecord,
    DecisionRequest,
    Incident,
    IncidentCreate,
    IncidentStatus,
    ProposalStatus,
    RemediationProposal,
)
from incidentpilot.shared.config import AgentSettings
from incidentpilot.shared.http import configure_http
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics
from incidentpilot.shared.telemetry import configure_telemetry


def create_app(
    settings: AgentSettings | None = None,
    *,
    provider: LLMProvider | None = None,
    store: IncidentStore | None = None,
    tools: EvidenceTools | None = None,
) -> FastAPI:
    config = settings or AgentSettings()
    metrics = Metrics(config.service_name)
    agent_metrics = AgentMetrics(metrics.registry)
    owned_store = store is None
    owned_tools = tools is None
    incident_store = store or IncidentStore(
        config.data_url, config.internal_token.get_secret_value(), config.http_timeout
    )
    evidence_tools = tools or EvidenceTools(config.evidence_url, config.http_timeout)
    provider_was_injected = provider is not None
    configured_provider = provider
    if configured_provider is None and config.llm_provider == "openai":
        try:
            configured_provider = OpenAIProvider(
                config.llm_api_key.get_secret_value() if config.llm_api_key else "",
                config.llm_model,
                config.llm_timeout,
                config.llm_max_output_tokens,
                config.llm_temperature,
            )
        except ProviderError:
            configured_provider = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config)
        try:
            yield
        finally:
            if owned_store:
                incident_store.close()
            if owned_tools:
                evidence_tools.close()
            telemetry.shutdown()

    app = FastAPI(title="IncidentPilot investigation service", lifespan=lifespan)
    telemetry = configure_telemetry(config, app)
    configure_http(app)
    metrics.install(app)

    def internal(x_internal_token: Annotated[str | None, Header()] = None) -> None:
        if not secrets.compare_digest(
            (x_internal_token or "").encode(), config.internal_token.get_secret_value().encode()
        ):
            raise HTTPException(401, "internal credential required")

    def find_proposal(incident: Incident, proposal_id: UUID) -> RemediationProposal:
        proposal = next(
            (item for item in incident.remediation_proposals if item.proposal_id == proposal_id),
            None,
        )
        if proposal is None:
            raise HTTPException(404, "proposal_not_found")
        return proposal

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            incident_store.http.get("/ready").raise_for_status()
            evidence_tools.http.get("/ready").raise_for_status()
        except Exception as exc:
            raise HTTPException(503, "dependency_unavailable") from exc
        return {"status": "ready"}

    @app.post("/v1/incidents", status_code=201, dependencies=[Depends(internal)])
    def create_incident(body: IncidentCreate) -> Incident:
        incident = Incident(**body.model_dump())
        incident_store.create(incident)
        audit = incident_store.audit(incident.incident_id, "incident_created", "operator")
        incident.audit_references.append(audit.audit_id)
        return incident_store.update(incident)

    @app.get("/v1/incidents/{incident_id}", dependencies=[Depends(internal)])
    def get_incident(incident_id: UUID) -> Incident:
        return incident_store.get(incident_id)

    @app.post("/v1/incidents/{incident_id}/investigate", dependencies=[Depends(internal)])
    def investigate(incident_id: UUID) -> Incident:
        if configured_provider is None or (
            isinstance(configured_provider, FakeProvider) and not provider_was_injected
        ):
            raise HTTPException(503, "real_llm_provider_not_configured")
        incident = incident_store.get(incident_id)
        if incident.status != IncidentStatus.OPEN:
            raise HTTPException(409, "incident_not_open")
        start_audit = incident_store.audit(incident_id, "investigation_started", "incident-agent")
        incident.audit_references.append(start_audit.audit_id)
        engine = InvestigationEngine(
            configured_provider,
            evidence_tools,
            max_turns=config.investigation_max_turns,
            max_tool_calls=config.investigation_max_tool_calls,
            max_seconds=config.investigation_max_seconds,
            max_evidence_bytes=config.investigation_max_evidence_bytes,
        )
        started = time.monotonic()
        agent_metrics.investigations.labels("started").inc()
        try:
            incident = engine.run(incident)
        except InvestigationError as exc:
            agent_metrics.investigations.labels("failed").inc()
            agent_metrics.llm_requests.labels("failed").inc()
            failed = incident_store.audit(
                incident_id, "investigation_failed", "incident-agent", {"reason": str(exc)}
            )
            incident.audit_references.append(failed.audit_id)
            incident_store.update(incident)
            raise HTTPException(502, str(exc)) from exc
        finally:
            agent_metrics.duration.observe(time.monotonic() - started)
        for step in incident.investigation_steps:
            queried = incident_store.audit(
                incident_id,
                "evidence_queried",
                "incident-agent",
                {
                    "step": step.step_number,
                    "tool": step.requested_evidence_action.tool,
                    "evidence_ids": [str(value) for value in step.evidence_ids],
                },
            )
            returned = incident_store.audit(
                incident_id,
                "evidence_returned",
                "incident-agent",
                {
                    "step": step.step_number,
                    "evidence_ids": [str(value) for value in step.evidence_ids],
                },
            )
            hypothesis = incident_store.audit(
                incident_id,
                "hypothesis_updated",
                "incident-agent",
                {"step": step.step_number, "disposition": step.disposition.value},
            )
            incident.audit_references.extend(
                [queried.audit_id, returned.audit_id, hypothesis.audit_id]
            )
            agent_metrics.evidence_calls.labels("success").inc()
        agent_metrics.llm_requests.labels("success").inc(incident.investigation_turns)
        diagnosis_audit = incident_store.audit(
            incident_id,
            "diagnosis_created",
            "incident-agent",
            {"diagnosis_id": str(incident.diagnosis.diagnosis_id) if incident.diagnosis else None},
        )
        proposal_audit = incident_store.audit(
            incident_id,
            "proposal_created",
            "incident-agent",
            {"proposal_id": str(incident.remediation_proposals[0].proposal_id)},
        )
        incident.audit_references.extend([diagnosis_audit.audit_id, proposal_audit.audit_id])
        agent_metrics.investigations.labels("completed").inc()
        agent_metrics.proposals.inc()
        return incident_store.update(incident)

    @app.get("/v1/incidents/{incident_id}/investigation", dependencies=[Depends(internal)])
    def investigation(incident_id: UUID) -> dict[str, object]:
        incident = incident_store.get(incident_id)
        return {
            "status": incident.status,
            "steps": incident.investigation_steps,
            "diagnosis": incident.diagnosis,
            "tool_call_count": incident.tool_call_count,
            "turns": incident.investigation_turns,
        }

    @app.get("/v1/incidents/{incident_id}/proposals", dependencies=[Depends(internal)])
    def proposals(incident_id: UUID) -> list[RemediationProposal]:
        return incident_store.get(incident_id).remediation_proposals

    def decide(
        incident_id: UUID, proposal_id: UUID, body: DecisionRequest, decision: str
    ) -> Incident:
        incident = incident_store.get(incident_id)
        proposal = find_proposal(incident, proposal_id)
        if proposal.status != ProposalStatus.PROPOSED:
            raise HTTPException(409, "proposal_already_decided")
        if proposal_hash(proposal) != proposal.proposal_hash:
            raise HTTPException(409, "proposal_hash_mismatch")
        approval = ApprovalRecord(
            proposal_id=proposal_id,
            proposal_hash=proposal.proposal_hash,
            approver_identity=body.approver_identity,
            decision=decision,
        )
        incident.approvals.append(approval)
        proposal.status = (
            ProposalStatus.APPROVED if decision == "approved" else ProposalStatus.REJECTED
        )
        if decision == "approved":
            incident.status = IncidentStatus.APPROVED
        audit = incident_store.audit(
            incident_id,
            f"proposal_{decision}",
            body.approver_identity,
            {"proposal_id": str(proposal_id), "proposal_hash": proposal.proposal_hash},
        )
        incident.audit_references.append(audit.audit_id)
        agent_metrics.decisions.labels(decision).inc()
        return incident_store.update(incident)

    @app.post(
        "/v1/incidents/{incident_id}/proposals/{proposal_id}/approve",
        dependencies=[Depends(internal)],
    )
    def approve(incident_id: UUID, proposal_id: UUID, body: DecisionRequest) -> Incident:
        return decide(incident_id, proposal_id, body, "approved")

    @app.post(
        "/v1/incidents/{incident_id}/proposals/{proposal_id}/reject",
        dependencies=[Depends(internal)],
    )
    def reject(incident_id: UUID, proposal_id: UUID, body: DecisionRequest) -> Incident:
        return decide(incident_id, proposal_id, body, "rejected")

    @app.get("/v1/incidents/{incident_id}/audit/verify", dependencies=[Depends(internal)])
    def verify_audit(incident_id: UUID) -> dict[str, object]:
        records = incident_store.audits(incident_id)
        return {"valid": verify_chain(records), "records": len(records)}

    return app
