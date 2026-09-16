import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from incidentpilot.agent.prompts import SYSTEM_POLICY, investigation_prompt
from incidentpilot.agent.provider import LLMProvider, ProviderError, RemediationDraft
from incidentpilot.agent.tools import EvidenceToolError, EvidenceTools
from incidentpilot.incidents.approval import proposal_hash
from incidentpilot.incidents.models import (
    HypothesisDisposition,
    Incident,
    IncidentStatus,
    InvestigationStep,
    Reflection,
    RemediationProposal,
)


class InvestigationError(RuntimeError):
    pass


class InvestigationEngine:
    def __init__(
        self,
        provider: LLMProvider,
        tools: EvidenceTools,
        *,
        max_turns: int,
        max_tool_calls: int,
        max_seconds: int,
        max_evidence_bytes: int,
        max_provider_calls: int | None = None,
        max_input_tokens: int | None = None,
        max_total_tokens: int | None = None,
        max_context_bytes: int | None = None,
        provider_retry_limit: int = 0,
        provider_retry_backoff_seconds: float = 0,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
        cost_currency: str = "USD",
        pricing_source_version: str | None = None,
        max_cost: float | None = None,
        max_evidence_items: int | None = None,
        max_evidence_payload_bytes: int | None = None,
    ) -> None:
        self.provider, self.tools = provider, tools
        self.max_turns, self.max_tool_calls = max_turns, max_tool_calls
        self.max_seconds, self.max_evidence_bytes = max_seconds, max_evidence_bytes
        self.max_provider_calls = max_provider_calls or max_turns
        self.max_input_tokens, self.max_total_tokens = max_input_tokens, max_total_tokens
        self.max_context_bytes = max_context_bytes
        self.provider_retry_limit = provider_retry_limit
        self.provider_retry_backoff_seconds = provider_retry_backoff_seconds
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self.cost_currency, self.pricing_source_version = cost_currency, pricing_source_version
        self.max_cost = max_cost
        self.max_evidence_items = max_evidence_items or max_tool_calls
        self.max_evidence_payload_bytes = max_evidence_payload_bytes

    def run(self, incident: Incident) -> Incident:
        started = time.monotonic()
        incident.status = IncidentStatus.INVESTIGATING
        incident.investigation_started_at = datetime.now(UTC)
        incident.provider, incident.model = self.provider.name, self.provider.model
        for turn in range(1, self.max_turns + 1):
            if time.monotonic() - started > self.max_seconds:
                raise InvestigationError("investigation wall-clock limit reached")
            if incident.provider_request_count >= self.max_provider_calls:
                raise InvestigationError("provider-call budget reached")
            if (
                self.max_cost is not None
                and incident.estimated_cost_usd is not None
                and incident.estimated_cost_usd >= self.max_cost
            ):
                raise InvestigationError("cost budget reached")
            prompt = investigation_prompt(incident)
            if self.max_context_bytes is not None and len(prompt.encode()) > self.max_context_bytes:
                raise InvestigationError("context budget reached")
            for attempt in range(self.provider_retry_limit + 1):
                try:
                    decision = self.provider.decide(SYSTEM_POLICY, prompt)
                    break
                except ProviderError as exc:
                    incident.provider_error_category = exc.category.value
                    if not exc.retryable or attempt >= self.provider_retry_limit:
                        raise InvestigationError(f"provider failure: {exc.category.value}") from exc
                    incident.provider_retry_count += 1
                    if self.provider_retry_backoff_seconds:
                        time.sleep(self.provider_retry_backoff_seconds)
            incident.investigation_turns = turn
            incident.provider_request_count += 1
            if decision.input_tokens is not None:
                incident.input_tokens = (incident.input_tokens or 0) + decision.input_tokens
            if decision.output_tokens is not None:
                incident.output_tokens = (incident.output_tokens or 0) + decision.output_tokens
            if self.input_cost_per_million is not None and self.output_cost_per_million is not None:
                incident.input_cost = (
                    (incident.input_tokens or 0) * self.input_cost_per_million / 1_000_000
                )
                incident.output_cost = (
                    (incident.output_tokens or 0) * self.output_cost_per_million / 1_000_000
                )
                incident.estimated_cost_usd = incident.input_cost + incident.output_cost
                incident.cost_currency = self.cost_currency
                incident.pricing_source_version = self.pricing_source_version
                if self.max_cost is not None and incident.estimated_cost_usd > self.max_cost:
                    raise InvestigationError("cost budget reached")
            if (
                self.max_input_tokens is not None
                and (incident.input_tokens or 0) > self.max_input_tokens
            ):
                raise InvestigationError("input-token budget reached")
            if self.max_total_tokens is not None and (
                (incident.input_tokens or 0) + (incident.output_tokens or 0) > self.max_total_tokens
            ):
                raise InvestigationError("total-token budget reached")
            if incident.investigation_steps:
                previous = incident.investigation_steps[-1]
                previous.current_hypothesis = decision.hypothesis
                previous.observation = decision.observation
                previous.disposition = HypothesisDisposition(decision.disposition)
            if decision.diagnosis:
                known = {
                    item for step in incident.investigation_steps for item in step.evidence_ids
                }
                cited = set(decision.diagnosis.supporting_evidence_ids) | set(
                    decision.diagnosis.contradicting_evidence_ids
                )
                if not cited.issubset(known) or not decision.diagnosis.supporting_evidence_ids:
                    raise InvestigationError("diagnosis contains unsupported evidence references")
                incident.diagnosis = decision.diagnosis
                incident.reflection = Reflection(
                    leading_hypothesis=decision.hypothesis,
                    current_evidence_ids=decision.diagnosis.supporting_evidence_ids,
                    contradicting_evidence_ids=decision.diagnosis.contradicting_evidence_ids,
                    historical_memory_ids=tuple(
                        UUID(value) for value in incident.historical_memory
                    ),
                    additional_evidence_warranted=False,
                )
                incident.status = IncidentStatus.DIAGNOSED
                incident.investigation_completed_at = datetime.now(UTC)
                incident.remediation_proposals = [self._proposal(incident, decision.remediation)]
                incident.status = IncidentStatus.PROPOSAL_READY
                return incident
            if not decision.action:
                raise InvestigationError("provider returned neither evidence action nor diagnosis")
            if incident.tool_call_count >= self.max_tool_calls:
                raise InvestigationError("evidence tool-call limit reached")
            try:
                evidence = self.tools.execute(decision.action)
            except EvidenceToolError as exc:
                raise InvestigationError("evidence backend failure") from exc
            payload = evidence.model_dump(mode="json")
            if (
                self.max_evidence_payload_bytes is not None
                and len(json.dumps(payload)) > self.max_evidence_payload_bytes
            ):
                raise InvestigationError("evidence payload budget reached")
            if len(incident.evidence) >= self.max_evidence_items:
                raise InvestigationError("evidence-item budget reached")
            if (
                sum(len(json.dumps(value)) for value in incident.evidence.values())
                + len(json.dumps(payload))
                > self.max_evidence_bytes
            ):
                raise InvestigationError("evidence retention limit reached")
            evidence_id = evidence.provenance.evidence_id
            incident.evidence[str(evidence_id)] = payload
            incident.tool_call_count += 1
            incident.investigation_steps.append(
                InvestigationStep(
                    step_number=len(incident.investigation_steps) + 1,
                    timestamp=datetime.now(UTC),
                    current_hypothesis=decision.hypothesis,
                    requested_evidence_action=decision.action,
                    evidence_ids=(evidence_id,),
                    observation=decision.observation,
                    disposition=HypothesisDisposition(decision.disposition),
                )
            )
        raise InvestigationError("investigation turn limit reached")

    def _proposal(self, incident: Incident, data: RemediationDraft | None) -> RemediationProposal:
        if not incident.diagnosis:
            raise InvestigationError("proposal requires a diagnosis")
        values: dict[str, Any] = data.model_dump() if data else {}
        proposal = RemediationProposal(
            incident_id=incident.incident_id,
            diagnosis_reference=incident.diagnosis.diagnosis_id,
            proposed_action_type=values.get("proposed_action_type", "investigate_manually"),
            target_service=values.get("target_service", incident.diagnosis.affected_service),
            description=values.get(
                "description", "Have an operator investigate the diagnosed condition."
            ),
            rationale=values.get("rationale", incident.diagnosis.concise_explanation),
            expected_effect=values.get(
                "expected_effect", "Operator validates and addresses the condition."
            ),
            risk=values.get("risk", "Requires human assessment before any action."),
            rollback_plan=values.get("rollback_plan", "No automated change is performed."),
            verification_plan=values.get(
                "verification_plan", "Re-query read-only service evidence."
            ),
            proposal_hash="0" * 64,
        )
        proposal.proposal_hash = proposal_hash(proposal)
        return proposal
