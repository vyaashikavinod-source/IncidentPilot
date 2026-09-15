from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from incidentpilot.chaos.catalog import load_ground_truth, load_scenarios
from incidentpilot.evaluation.models import (
    AgentScenarioResult,
    DiagnosisSubmission,
    ManualDiagnosis,
)
from incidentpilot.evaluation.recording import record_manual_diagnosis
from incidentpilot.evaluation.scoring import aggregate, aggregate_agent, score


def submission(**updates: object) -> DiagnosisSubmission:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "run_id": uuid4(),
        "scenario_id": "worker-stopped",
        "submitted_root_cause": "Celery worker is stopped",
        "submitted_affected_service": "worker",
        "submitted_failure_class": "service unavailable",
        "evidence_references": ("services", "logs"),
        "diagnosis_started_at": now,
        "diagnosis_completed_at": now + timedelta(seconds=12),
    }
    return DiagnosisSubmission.model_validate({**values, **updates})


def test_deterministic_score_and_unsupported_reference() -> None:
    truth = load_ground_truth(load_scenarios()["worker-stopped"])
    result = score(submission(), truth, {"services", "logs"})
    assert result.passed
    assert result.diagnosis_latency_seconds == 12
    assert result.evidence_reference_count == 2
    unsupported = score(submission(evidence_references=("database",)), truth, {"services"})
    assert unsupported.unsupported_evidence_references == ("database",)
    assert not unsupported.passed


def test_aggregate_reports_accuracy_latency_and_failure_class() -> None:
    truth = load_ground_truth(load_scenarios()["worker-stopped"])
    passed = score(submission(), truth, {"services", "logs"})
    failed = score(submission(submitted_root_cause="unknown"), truth, {"services", "logs"})
    report = aggregate([passed, failed], {truth.scenario_id: truth})
    assert report.accuracy == 0.5
    assert report.scenario_pass_rate == 0.5
    assert report.median_diagnosis_time_seconds == 12
    assert report.failure_breakdown == {"service_unavailable": 1}
    with pytest.raises(ValueError):
        aggregate([], {})


def test_manual_baseline_requires_participant_and_ordered_times() -> None:
    payload = submission().model_dump()
    manual = ManualDiagnosis.model_validate({**payload, "participant_id": "engineer-01"})
    assert manual.participant_id == "engineer-01"
    with pytest.raises(ValidationError):
        ManualDiagnosis.model_validate({**payload, "participant_id": ""})
    with pytest.raises(ValidationError):
        DiagnosisSubmission.model_validate(
            {
                **payload,
                "diagnosis_completed_at": payload["diagnosis_started_at"] - timedelta(seconds=1),
            }
        )


def test_manual_diagnosis_record_is_stable_and_excludes_ground_truth(tmp_path: Path) -> None:
    payload = submission().model_dump()
    diagnosis = ManualDiagnosis.model_validate({**payload, "participant_id": "engineer-01"})
    output = tmp_path / "manual-diagnosis.json"

    record_manual_diagnosis(output, diagnosis)

    contents = output.read_text(encoding="utf-8")
    assert contents.endswith("\n")
    assert '"participant_id": "engineer-01"' in contents
    assert "ground_truth" not in contents


def test_agent_aggregate_reports_phase_three_quality_gates() -> None:
    truth = load_ground_truth(load_scenarios()["worker-stopped"])
    passed = score(submission(), truth, {"services", "logs"})
    failed = score(submission(submitted_root_cause="unknown"), truth, {"services", "logs"})
    report = aggregate_agent(
        [
            AgentScenarioResult(
                score=passed,
                provider="real",
                model="model",
                confidence=0.8,
                investigation_turns=2,
                tool_call_count=2,
                proposal_produced=True,
            ),
            AgentScenarioResult(
                score=failed,
                provider="real",
                model="model",
                confidence=0.4,
                investigation_turns=3,
                tool_call_count=4,
                proposal_produced=True,
            ),
        ]
    )
    assert report.root_cause_accuracy == 0.5
    assert report.affected_service_accuracy == 1
    assert report.failure_class_accuracy == 1
    assert report.median_tool_calls == 3
    assert report.failures == ("worker-stopped",)
