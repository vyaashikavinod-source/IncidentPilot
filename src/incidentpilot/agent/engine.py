import json
import time
from datetime import UTC, datetime
from typing import Any

from incidentpilot.agent.prompts import SYSTEM_POLICY, investigation_prompt
from incidentpilot.agent.provider import LLMProvider, ProviderError
from incidentpilot.agent.tools import EvidenceToolError, EvidenceTools
from incidentpilot.incidents.approval import proposal_hash
from incidentpilot.incidents.models import (
    HypothesisDisposition,
    Incident,
    IncidentStatus,
    InvestigationStep,
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
    ) -> None:
        self.provider, self.tools = provider, tools
        self.max_turns, self.max_tool_calls = max_turns, max_tool_calls
        self.max_seconds, self.max_evidence_bytes = max_seconds, max_evidence_bytes

    def run(self, incident: Incident) -> Incident:
        started = time.monotonic()
        incident.status = IncidentStatus.INVESTIGATING
        incident.investigation_started_at = datetime.now(UTC)
        incident.provider, incident.model = self.provider.name, self.provider.model
        for turn in range(1, self.max_turns + 1):
            if time.monotonic() - started > self.max_seconds:
                raise InvestigationError("investigation wall-clock limit reached")
            try:
                decision = self.provider.decide(SYSTEM_POLICY, investigation_prompt(incident))
            except ProviderError as exc:
                raise InvestigationError("provider failure") from exc
            incident.investigation_turns = turn
            if decision.input_tokens is not None:
                incident.input_tokens = (incident.input_tokens or 0) + decision.input_tokens
            if decision.output_tokens is not None:
                incident.output_tokens = (incident.output_tokens or 0) + decision.output_tokens
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

    def _proposal(self, incident: Incident, data: dict[str, str] | None) -> RemediationProposal:
        if not incident.diagnosis:
            raise InvestigationError("proposal requires a diagnosis")
        values: dict[str, Any] = data or {}
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
