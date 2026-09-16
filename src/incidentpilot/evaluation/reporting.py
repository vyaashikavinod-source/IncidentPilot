import statistics

from incidentpilot.evaluation.models import AgentScenarioResult, Score


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
