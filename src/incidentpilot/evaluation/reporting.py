import statistics

from incidentpilot.evaluation.models import AgentScenarioResult, Score
from incidentpilot.evaluation.persistence import EvaluationRun, EvaluationScenarioResult


def comparison_report(
    agent_results: list[AgentScenarioResult], manual_scores: list[Score]
) -> dict[str, object]:
    """Compare only recorded observations; never infer absent human results."""
    report: dict[str, object] = {
        "agent_sample_size": len(agent_results),
        "manual_sample_size": len(manual_scores),
    }
    if not manual_scores:
        report["manual_baseline_status"] = "MANUAL BASELINE PENDING — NO RECORDED HUMAN RUNS"
        return report
    report["manual_baseline_status"] = "recorded"
    report["manual_root_cause_accuracy"] = sum(
        item.root_cause_correct for item in manual_scores
    ) / len(manual_scores)
    report["manual_median_duration_seconds"] = statistics.median(
        item.diagnosis_latency_seconds for item in manual_scores
    )
    if agent_results:
        scores = [item.score for item in agent_results]
        report["agent_root_cause_accuracy"] = sum(item.root_cause_correct for item in scores) / len(
            scores
        )
        report["agent_median_duration_seconds"] = statistics.median(
            item.diagnosis_latency_seconds for item in scores
        )
    return report


def manual_submission_template(
    run_id: str, scenario_id: str, participant_id: str
) -> dict[str, str]:
    """A blinded operator form: callers supply evidence and diagnosis before scoring."""
    return {"run_id": run_id, "scenario_id": scenario_id, "participant_id": participant_id}


def evaluation_report(run: EvaluationRun) -> dict[str, object]:
    """Produce a deterministic report from one persisted, completed evaluation run."""
    if run.status != "completed":
        raise ValueError("evaluation reports require a completed evaluation run")
    return _aggregate_results(run.scenario_results, include_breakdowns=True)


def _aggregate_results(
    results: list[EvaluationScenarioResult], *, include_breakdowns: bool
) -> dict[str, object]:
    if not results:
        raise ValueError("evaluation reports require at least one scenario result")
    durations = [item.duration_seconds for item in results]
    report: dict[str, object] = {
        "sample_size": len(results),
        "root_cause_accuracy": _rate(results, "root_cause_correct"),
        "affected_service_accuracy": _rate(results, "affected_service_correct"),
        "failure_class_accuracy": _rate(results, "failure_class_correct"),
        "scenario_pass_rate": sum(
            item.root_cause_correct and item.affected_service_correct and item.failure_class_correct
            for item in results
        )
        / len(results),
        "median_investigation_duration_seconds": statistics.median(durations),
        "p95_investigation_duration_seconds": _percentile_95(durations),
        "median_evidence_calls": statistics.median(item.evidence_calls for item in results),
        "median_memory_lookups": statistics.median(item.memory_calls for item in results),
        "unsupported_reference_rate": sum(item.unsupported_reference for item in results)
        / len(results),
        "total_provider_calls": sum(item.provider_calls for item in results),
        "total_input_tokens": _sum_if_available(results, "input_tokens"),
        "total_output_tokens": _sum_if_available(results, "output_tokens"),
        "total_tokens": _sum_if_available(results, "total_tokens"),
        "total_cost": _sum_if_available(results, "total_cost"),
    }
    if include_breakdowns:
        report.update(
            {
                "by_scenario": {
                    item.scenario_id: _aggregate_results([item], include_breakdowns=False)
                    for item in results
                },
                "by_affected_service": _breakdown(results, "affected_service"),
                "by_failure_class": _breakdown(results, "failure_class"),
            }
        )
    return report


def _rate(results: list[EvaluationScenarioResult], field: str) -> float:
    return sum(bool(getattr(item, field)) for item in results) / len(results)


def _sum_if_available(results: list[EvaluationScenarioResult], field: str) -> int | float | None:
    values = [getattr(item, field) for item in results]
    return None if any(value is None for value in values) else sum(values)


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * 0.95)))
    return ordered[index]


def _breakdown(results: list[EvaluationScenarioResult], field: str) -> dict[str, dict[str, object]]:
    buckets: dict[str, list[EvaluationScenarioResult]] = {}
    for item in results:
        buckets.setdefault(getattr(item, field) or "unreported", []).append(item)
    return {
        name: _aggregate_results(items, include_breakdowns=False)
        for name, items in sorted(buckets.items())
    }
