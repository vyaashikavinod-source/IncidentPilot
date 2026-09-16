from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from incidentpilot.evaluation.persistence import EvaluationRun, EvaluationScenarioResult
from incidentpilot.evaluation.reporting import evaluation_report


def _result(*, scenario_id: str = "scenario-a", duration: float = 4.0) -> EvaluationScenarioResult:
    return EvaluationScenarioResult(
        scenario_id=scenario_id,
        root_cause_correct=True,
        affected_service_correct=True,
        failure_class_correct=False,
        confidence=0.8,
        investigation_turns=2,
        evidence_calls=3,
        memory_calls=1,
        provider_calls=2,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        duration_seconds=duration,
        affected_service="data",
        failure_class="timeout",
    )


def test_completed_evaluation_requires_results_and_timestamp() -> None:
    with pytest.raises(ValidationError):
        EvaluationRun(
            repository_commit="abcdef0",
            provider="configured-provider",
            model="configured-model",
            memory_enabled=True,
            status="completed",
        )


def test_report_preserves_unavailable_cost_and_breaks_down_results() -> None:
    run = EvaluationRun(
        repository_commit="abcdef0",
        provider="configured-provider",
        model="configured-model",
        memory_enabled=True,
        status="completed",
        completed_at=datetime.now(UTC),
        scenario_results=[_result(), _result(scenario_id="scenario-b", duration=8.0)],
    )
    report = evaluation_report(run)
    assert report["total_cost"] is None
    assert report["root_cause_accuracy"] == 1.0
    assert report["by_scenario"]
    assert report["by_affected_service"]


def test_scenario_token_totals_cannot_be_inconsistent() -> None:
    with pytest.raises(ValidationError, match="total_tokens"):
        EvaluationScenarioResult(
            scenario_id="scenario-a",
            root_cause_correct=True,
            affected_service_correct=True,
            failure_class_correct=True,
            confidence=0.8,
            investigation_turns=1,
            evidence_calls=1,
            memory_calls=1,
            provider_calls=1,
            input_tokens=2,
            output_tokens=3,
            total_tokens=1,
            duration_seconds=1,
        )
