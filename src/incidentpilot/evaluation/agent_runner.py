"""Operator-side blinded bridge from Phase 2 chaos runs to Phase 3 investigation."""

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx

from incidentpilot.chaos.catalog import load_ground_truth
from incidentpilot.chaos.executor import RunExecutor
from incidentpilot.chaos.models import Scenario
from incidentpilot.evaluation.models import AgentScenarioResult, DiagnosisSubmission
from incidentpilot.evaluation.scoring import score
from incidentpilot.incidents.models import Incident


class AgentEvaluationRunner:
    def __init__(
        self,
        root: Path,
        control_plane_url: str,
        agent_url: str,
        internal_token: str,
        runs_dir: Path,
    ) -> None:
        self.executor = RunExecutor(root, control_plane_url, runs_dir)
        self.agent = httpx.Client(
            base_url=agent_url, headers={"X-Internal-Token": internal_token}, timeout=120
        )
        self.runs_dir = runs_dir

    def run(self, scenario: Scenario) -> tuple[Incident, AgentScenarioResult]:
        captured: dict[str, Any] = {}

        def investigate(run_id: UUID) -> dict[str, Any]:
            created = self.agent.post(
                "/v1/incidents",
                json={
                    "source": "phase2-evaluation",
                    "title": "Sandbox service degradation",
                    "description": (
                        "One or more monitored services are degraded. Diagnose using evidence."
                    ),
                    "severity": scenario.severity,
                    "alert_metadata": {"chaos_run_id": str(run_id)},
                },
            )
            created.raise_for_status()
            incident_id = created.json()["incident_id"]
            response = self.agent.post(f"/v1/incidents/{incident_id}/investigate")
            response.raise_for_status()
            captured.update(cast(dict[str, Any], response.json()))
            return captured

        manifest = self.executor.run(scenario, during_fault=investigate)
        incident = Incident.model_validate(captured)
        if (
            incident.diagnosis is None
            or incident.investigation_started_at is None
            or incident.investigation_completed_at is None
        ):
            raise RuntimeError("agent investigation completed without a persisted diagnosis")
        # Hidden truth is loaded only after investigation has ended and the scenario recovered.
        truth = load_ground_truth(scenario)
        submission = DiagnosisSubmission(
            run_id=manifest.run_id,
            scenario_id=scenario.scenario_id,
            submitted_root_cause=incident.diagnosis.likely_root_cause,
            submitted_affected_service=incident.diagnosis.affected_service,
            submitted_failure_class=incident.diagnosis.failure_class,
            evidence_references=tuple(
                str(value) for value in incident.diagnosis.supporting_evidence_ids
            ),
            diagnosis_started_at=incident.investigation_started_at,
            diagnosis_completed_at=incident.investigation_completed_at,
            confidence=incident.diagnosis.confidence,
        )
        scored = score(submission, truth, set(incident.evidence))
        result = AgentScenarioResult(
            score=scored,
            provider=incident.provider or "unknown",
            model=incident.model or "unknown",
            confidence=incident.diagnosis.confidence,
            investigation_turns=incident.investigation_turns,
            tool_call_count=incident.tool_call_count,
            input_tokens=incident.input_tokens,
            output_tokens=incident.output_tokens,
            proposal_produced=bool(incident.remediation_proposals),
        )
        output = self.runs_dir / str(manifest.run_id) / "agent-score.json"
        output.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
        return incident, result
