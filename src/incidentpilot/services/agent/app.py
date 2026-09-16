import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException

from incidentpilot.agent.engine import InvestigationEngine, InvestigationError
from incidentpilot.agent.metrics import AgentMetrics
from incidentpilot.agent.persistence import IncidentStore, IncidentStoreError
from incidentpilot.agent.provider import FakeProvider, LLMProvider, OpenAIProvider, ProviderError
from incidentpilot.agent.tools import EvidenceTools
from incidentpilot.incidents.approval import proposal_hash
from incidentpilot.incidents.audit import AuditCheckpoint, AuditRecord, ChainVerification
from incidentpilot.incidents.models import (
    ApprovalDecisionCommand,
    DecisionRequest,
    Incident,
    IncidentCreate,
    IncidentStatus,
    RemediationProposal,
)
from incidentpilot.memory.models import MemoryQuery, MemorySearchResult
from incidentpilot.security.auth import OperatorAuthenticator, OperatorIdentity, Role, require_role
from incidentpilot.security.rate_limit import LocalRateLimiter, RateLimitExceeded
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
    security_metrics = AgentMetrics(metrics.registry)
    authenticator = OperatorAuthenticator(
        config.operator_signing_secret.get_secret_value(),
        config.operator_token_issuer,
        config.operator_token_audience,
    )
    limiter = LocalRateLimiter()
    owned_store, owned_tools = store is None, tools is None
    incident_store = store or IncidentStore(
        config.data_url, config.data_token.get_secret_value(), config.http_timeout
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

    def operator(
        authorization: Annotated[str | None, Header()] = None,
    ) -> OperatorIdentity:
        try:
            return authenticator.authenticate(authorization)
        except HTTPException:
            security_metrics.security_events.labels("authentication_failure").inc()
            logging.getLogger("incidentpilot.security").warning("operator_authentication_failed")
            raise

    def authorize(
        identity: OperatorIdentity,
        role: Role,
        incident_id: UUID | None = None,
    ) -> None:
        try:
            require_role(identity, role)
        except HTTPException:
            security_metrics.security_events.labels("authorization_denial").inc()
            logging.getLogger("incidentpilot.security").warning(
                "operator_authorization_denied", extra={"required_role": role.value}
            )
            if incident_id:
                with suppress(IncidentStoreError):
                    incident_store.audit(
                        incident_id,
                        "authorization_denied",
                        identity.subject,
                        {"required_role": role.value},
                    )
            raise

    def rate(identity: OperatorIdentity, operation: str, limit: int) -> None:
        try:
            limiter.check(f"{identity.token_id}:{operation}", limit, 60)
        except RateLimitExceeded as exc:
            security_metrics.security_events.labels("rate_limit_rejection").inc()
            raise HTTPException(429, str(exc)) from exc

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            incident_store.http.get("/ready").raise_for_status()
            evidence_tools.http.get("/ready").raise_for_status()
        except Exception as exc:
            raise HTTPException(503, "dependency_unavailable") from exc
        return {"status": "ready"}

    @app.post("/v1/incidents", status_code=201)
    def create_incident(
        body: IncidentCreate,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> Incident:
        authorize(identity, Role.INVESTIGATOR)
        rate(identity, "create", 10)
        incident = Incident(**body.model_dump())
        incident_store.create(incident)
        audit = incident_store.audit(
            incident.incident_id,
            "incident_created",
            identity.subject,
            {"source": body.source, "severity": body.severity},
        )
        incident.audit_references.append(audit.audit_id)
        return incident_store.update(incident)

    @app.get("/v1/incidents/{incident_id}")
    def get_incident(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> Incident:
        authorize(identity, Role.VIEWER, incident_id)
        return incident_store.get(incident_id)

    @app.post("/v1/incidents/{incident_id}/investigate")
    def investigate(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> Incident:
        authorize(identity, Role.INVESTIGATOR, incident_id)
        rate(identity, "investigate", 3)
        if configured_provider is None or (
            isinstance(configured_provider, FakeProvider) and not provider_was_injected
        ):
            incident_store.audit(
                incident_id,
                "investigation_rejected",
                identity.subject,
                {"reason": "real_provider_not_configured"},
            )
            raise HTTPException(503, "real_llm_provider_not_configured")
        try:
            incident = incident_store.claim(incident_id)
        except IncidentStoreError as exc:
            security_metrics.security_events.labels("state_conflict").inc()
            try:
                incident_store.audit(
                    incident_id,
                    "investigation_rejected",
                    identity.subject,
                    {"reason": "state_conflict"},
                )
            finally:
                raise HTTPException(exc.status or 503, "investigation claim failed") from exc
        start_audit = incident_store.audit(
            incident_id,
            "investigation_started",
            identity.subject,
            {"attempt": incident.investigation_attempts},
        )
        incident.audit_references.append(start_audit.audit_id)
        try:
            memories = incident_store.search_memory(
                MemoryQuery(affected_service=incident.affected_service_hint, limit=5)
            )
        except (IncidentStoreError, AttributeError):
            memories = []
        incident.historical_memory = {
            str(item.memory.memory_id): item.memory.model_dump(mode="json") for item in memories
        }
        security_metrics.memory_lookups.labels("hit" if memories else "miss").inc()
        memory_audit = incident_store.audit(
            incident_id, "memory_lookup", "incident-agent", {"result_count": len(memories)}
        )
        incident.audit_references.append(memory_audit.audit_id)
        engine = InvestigationEngine(
            configured_provider,
            evidence_tools,
            max_turns=config.investigation_max_turns,
            max_tool_calls=config.investigation_max_tool_calls,
            max_seconds=config.investigation_max_seconds,
            max_evidence_bytes=config.investigation_max_evidence_bytes,
            max_provider_calls=config.investigation_max_provider_calls,
            max_input_tokens=config.investigation_max_input_tokens,
            max_total_tokens=config.investigation_max_total_tokens,
        )
        started = time.monotonic()
        security_metrics.investigations.labels("started").inc()
        try:
            incident = engine.run(incident)
        except InvestigationError as exc:
            reason = str(exc)
            incident.status = IncidentStatus.INVESTIGATION_FAILED
            incident.investigation_completed_at = datetime.now(UTC)
            incident.last_failure_at = incident.investigation_completed_at
            incident.investigation_error = reason
            incident.budget_termination_reason = reason if "budget" in reason else None
            incident.investigation_lease_expires_at = None
            security_metrics.investigations.labels("failed").inc()
            security_metrics.llm_requests.labels("failed").inc()
            event = "investigation_limit" if "limit" in reason else "invalid_provider_output"
            if "budget" in reason:
                security_metrics.budget_terminations.labels(reason.replace(" ", "_")).inc()
            security_metrics.security_events.labels(event).inc()
            failed = incident_store.audit(
                incident_id, "investigation_failed", "incident-agent", {"reason": reason}
            )
            incident.audit_references.append(failed.audit_id)
            incident_store.update(incident)
            raise HTTPException(502, reason) from exc
        finally:
            security_metrics.duration.observe(time.monotonic() - started)
        incident.investigation_lease_expires_at = None
        _audit_completed_investigation(incident)
        incident = incident_store.update(incident)
        try:
            memory = incident_store.create_memory(incident.incident_id)
            created_memory = incident_store.audit(
                incident_id,
                "memory_created",
                "incident-agent",
                {"memory_id": str(memory.memory_id)},
            )
            incident.audit_references.append(created_memory.audit_id)
        except (IncidentStoreError, AttributeError):
            pass
        return incident_store.update(incident)

    def _audit_completed_investigation(incident: Incident) -> None:
        for step in incident.investigation_steps:
            audit_events: tuple[tuple[str, dict[str, object]], ...] = (
                (
                    "evidence_queried",
                    {"step": step.step_number, "tool": step.requested_evidence_action.tool},
                ),
                (
                    "evidence_returned",
                    {"step": step.step_number, "evidence_ids": [str(v) for v in step.evidence_ids]},
                ),
                (
                    "hypothesis_updated",
                    {"step": step.step_number, "disposition": step.disposition.value},
                ),
            )
            for event, metadata in audit_events:
                item = incident_store.audit(incident.incident_id, event, "incident-agent", metadata)
                incident.audit_references.append(item.audit_id)
            security_metrics.evidence_calls.labels("success").inc()
        security_metrics.llm_requests.labels("success").inc(incident.investigation_turns)
        diagnosis = incident_store.audit(
            incident.incident_id,
            "diagnosis_created",
            "incident-agent",
            {"diagnosis_id": str(incident.diagnosis.diagnosis_id) if incident.diagnosis else None},
        )
        proposal = incident_store.audit(
            incident.incident_id,
            "proposal_created",
            "incident-agent",
            {"proposal_id": str(incident.remediation_proposals[0].proposal_id)},
        )
        incident.audit_references.extend([diagnosis.audit_id, proposal.audit_id])
        security_metrics.investigations.labels("completed").inc()
        security_metrics.proposals.inc()

    @app.get("/v1/incidents/{incident_id}/investigation")
    def investigation(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> dict[str, object]:
        authorize(identity, Role.VIEWER, incident_id)
        incident = incident_store.get(incident_id)
        return {
            "status": incident.status,
            "steps": incident.investigation_steps,
            "diagnosis": incident.diagnosis,
            "tool_call_count": incident.tool_call_count,
            "turns": incident.investigation_turns,
            "error": incident.investigation_error,
            "last_failure_at": incident.last_failure_at,
        }

    @app.get("/v1/incidents/{incident_id}/proposals")
    def proposals(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> list[RemediationProposal]:
        authorize(identity, Role.VIEWER, incident_id)
        return incident_store.get(incident_id).remediation_proposals

    @app.get("/v1/memory")
    def memory_search(
        identity: Annotated[OperatorIdentity, Depends(operator)],
        affected_service: str | None = None,
        failure_class: str | None = None,
    ) -> list[MemorySearchResult]:
        authorize(identity, Role.VIEWER)
        return incident_store.search_memory(
            MemoryQuery(affected_service=affected_service, failure_class=failure_class)
        )

    def decide(
        incident_id: UUID,
        proposal_id: UUID,
        body: DecisionRequest,
        decision: Literal["approved", "rejected"],
        identity: OperatorIdentity,
    ) -> Incident:
        authorize(identity, Role.APPROVER, incident_id)
        rate(identity, "decision", 10)
        incident = incident_store.get(incident_id)
        previous = next(
            (item for item in incident.approvals if item.request_id == body.request_id), None
        )
        if previous is not None:
            if (
                previous.proposal_id == proposal_id
                and previous.proposal_hash == body.proposal_hash
                and previous.proposal_version == body.proposal_version
                and previous.decision == decision
                and previous.approver_identity == identity.subject
            ):
                return incident
            security_metrics.security_events.labels("approval_conflict").inc()
            raise HTTPException(409, "approval_request_replay_conflict")
        proposal = next(
            (item for item in incident.remediation_proposals if item.proposal_id == proposal_id),
            None,
        )
        if proposal is None or proposal.incident_id != incident_id:
            security_metrics.security_events.labels("approval_conflict").inc()
            incident_store.audit(
                incident_id,
                "approval_denied",
                identity.subject,
                {"reason": "wrong_proposal_binding"},
            )
            raise HTTPException(404, "proposal_not_found")
        if (
            body.proposal_hash != proposal.proposal_hash
            or body.proposal_version != proposal.version
            or proposal_hash(proposal) != body.proposal_hash
        ):
            security_metrics.security_events.labels("approval_conflict").inc()
            incident_store.audit(
                incident_id,
                "invalid_proposal_hash",
                identity.subject,
                {"proposal_id": str(proposal_id)},
            )
            raise HTTPException(409, "stale_or_invalid_proposal")
        command = ApprovalDecisionCommand(
            **body.model_dump(),
            proposal_id=proposal_id,
            approver_identity=identity.subject,
            decision=decision,
        )
        try:
            updated = incident_store.decide(incident_id, command)
        except IncidentStoreError as exc:
            security_metrics.security_events.labels("approval_conflict").inc()
            incident_store.audit(
                incident_id,
                "approval_denied",
                identity.subject,
                {"proposal_id": str(proposal_id), "reason": "state_or_replay_conflict"},
            )
            raise HTTPException(exc.status or 503, "approval decision rejected") from exc
        audit = incident_store.audit(
            incident_id,
            f"proposal_{decision}",
            identity.subject,
            {
                "proposal_id": str(proposal_id),
                "proposal_hash": proposal.proposal_hash,
                "proposal_version": proposal.version,
                "request_id": str(body.request_id),
            },
        )
        updated.audit_references.append(audit.audit_id)
        security_metrics.decisions.labels(decision).inc()
        return incident_store.update(updated)

    @app.post("/v1/incidents/{incident_id}/proposals/{proposal_id}/approve")
    def approve(
        incident_id: UUID,
        proposal_id: UUID,
        body: DecisionRequest,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> Incident:
        return decide(incident_id, proposal_id, body, "approved", identity)

    @app.post("/v1/incidents/{incident_id}/proposals/{proposal_id}/reject")
    def reject(
        incident_id: UUID,
        proposal_id: UUID,
        body: DecisionRequest,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> Incident:
        return decide(incident_id, proposal_id, body, "rejected", identity)

    @app.get("/v1/incidents/{incident_id}/audit")
    def audit_records(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> list[AuditRecord]:
        authorize(identity, Role.VIEWER, incident_id)
        return incident_store.audits(incident_id)

    @app.get("/v1/incidents/{incident_id}/audit/verify")
    def verify_audit(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> ChainVerification:
        authorize(identity, Role.VIEWER, incident_id)
        result = incident_store.verify_audit(incident_id)
        if not result.valid:
            security_metrics.security_events.labels("audit_verification_failure").inc()
        return result

    @app.get("/v1/audit/verify")
    def verify_all_audits(
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> dict[str, ChainVerification]:
        authorize(identity, Role.ADMIN)
        results = incident_store.verify_all_audits()
        if any(not result.valid for result in results.values()):
            security_metrics.security_events.labels("audit_verification_failure").inc()
        return results

    @app.post("/v1/incidents/{incident_id}/audit/checkpoints", status_code=201)
    def create_audit_checkpoint(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> AuditCheckpoint:
        authorize(identity, Role.ADMIN, incident_id)
        return incident_store.checkpoint(incident_id)

    @app.get("/v1/incidents/{incident_id}/audit/checkpoints/verify")
    def verify_audit_checkpoint(
        incident_id: UUID,
        identity: Annotated[OperatorIdentity, Depends(operator)],
    ) -> dict[str, bool]:
        authorize(identity, Role.VIEWER, incident_id)
        valid = incident_store.verify_checkpoint(incident_id)
        if not valid:
            security_metrics.security_events.labels("audit_verification_failure").inc()
        return {"valid": valid}

    return app
