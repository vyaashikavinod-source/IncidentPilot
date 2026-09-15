import statistics

from incidentpilot.chaos.models import GroundTruth
from incidentpilot.evaluation.models import (
    AgentAggregateReport,
    AgentScenarioResult,
    AggregateReport,
    DiagnosisSubmission,
    Score,
)


def normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def score(
    submission: DiagnosisSubmission,
    truth: GroundTruth,
    supported_evidence: set[str],
) -> Score:
    accepted = {
        normalize(truth.ground_truth_root_cause),
        *(normalize(x) for x in truth.acceptable_diagnoses),
    }
    root_correct = normalize(submission.submitted_root_cause) in accepted
    service_correct = normalize(submission.submitted_affected_service) == normalize(
        truth.affected_service
    )
    class_correct = normalize(submission.submitted_failure_class) == normalize(
        truth.failure_class.value
    )
    unsupported = tuple(
        ref for ref in submission.evidence_references if ref not in supported_evidence
    )
    return Score(
        run_id=submission.run_id,
        scenario_id=submission.scenario_id,
        root_cause_correct=root_correct,
        affected_service_correct=service_correct,
        failure_class_correct=class_correct,
        diagnosis_latency_seconds=(
            submission.diagnosis_completed_at - submission.diagnosis_started_at
        ).total_seconds(),
        evidence_reference_count=len(submission.evidence_references),
        unsupported_evidence_references=unsupported,
        passed=root_correct and service_correct and class_correct and not unsupported,
    )


def aggregate(scores: list[Score], truths: dict[str, GroundTruth]) -> AggregateReport:
    if not scores:
        raise ValueError("at least one score is required")
    failures: dict[str, int] = {}
    for result in scores:
        if not result.passed:
            key = truths[result.scenario_id].failure_class.value
            failures[key] = failures.get(key, 0) + 1
    return AggregateReport(
        scenario_count=len(scores),
        accuracy=sum(result.root_cause_correct for result in scores) / len(scores),
        scenario_pass_rate=sum(result.passed for result in scores) / len(scores),
        median_diagnosis_time_seconds=statistics.median(
            result.diagnosis_latency_seconds for result in scores
        ),
        failure_breakdown=failures,
    )


def aggregate_agent(results: list[AgentScenarioResult]) -> AgentAggregateReport:
    if not results:
        raise ValueError("at least one agent result is required")
    scores = [item.score for item in results]
    durations = sorted(item.diagnosis_latency_seconds for item in scores)
    rank = max(0, min(len(durations) - 1, int(0.95 * len(durations) + 0.999999) - 1))
    cited = sum(item.evidence_reference_count for item in scores)
    unsupported = sum(len(item.unsupported_evidence_references) for item in scores)
    count = len(results)
    return AgentAggregateReport(
        scenario_count=count,
        root_cause_accuracy=sum(item.root_cause_correct for item in scores) / count,
        affected_service_accuracy=sum(item.affected_service_correct for item in scores) / count,
        failure_class_accuracy=sum(item.failure_class_correct for item in scores) / count,
        scenario_pass_rate=sum(item.passed for item in scores) / count,
        median_investigation_time_seconds=statistics.median(durations),
        p95_investigation_time_seconds=durations[rank],
        median_tool_calls=statistics.median(item.tool_call_count for item in results),
        unsupported_evidence_reference_rate=unsupported / cited if cited else 0,
        failures=tuple(item.scenario_id for item in scores if not item.passed),
    )
