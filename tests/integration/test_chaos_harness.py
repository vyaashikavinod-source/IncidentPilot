import json
import os
import time
from collections.abc import Iterator

import httpx
import pytest

from incidentpilot.chaos.catalog import ROOT, load_scenarios
from incidentpilot.chaos.executor import RunExecutor

pytestmark = [pytest.mark.integration, pytest.mark.chaos_integration]


@pytest.fixture
def live_executor() -> Iterator[RunExecutor]:
    if os.getenv("INCIDENTPILOT_RUN_CHAOS_INTEGRATION") != "1":
        pytest.skip("set INCIDENTPILOT_RUN_CHAOS_INTEGRATION=1 for live fault injection")
    port = os.getenv("INCIDENTPILOT_CONTROL_PLANE_PORT", "8001")
    executor = RunExecutor(
        ROOT,
        f"http://127.0.0.1:{port}",
        ROOT / "evaluation" / "runs",
    )
    assert not executor.active_path.exists(), "recover the recorded active chaos run first"
    yield executor
    assert not executor.active_path.exists(), "chaos cleanup did not complete"


@pytest.mark.parametrize("scenario_id", sorted(load_scenarios()))
def test_allowlisted_scenario_is_observable_and_recovers(
    live_executor: RunExecutor, scenario_id: str
) -> None:
    scenario = load_scenarios()[scenario_id]
    manifest = live_executor.run(scenario)
    assert manifest.injection_result == "succeeded"
    assert manifest.recovery_result == "succeeded"
    assert manifest.scenario_status == "recovered"
    run_dir = live_executor.runs_dir / str(manifest.run_id)
    assert (run_dir / "manifest.json").is_file()
    evidence_text = (run_dir / "evidence.json").read_text()
    assert "ground_truth_root_cause" not in evidence_text
    evidence = json.loads(evidence_text)
    assert "services" in evidence["responses"]
    if scenario.affected_service in {"prometheus", "tempo"}:
        readiness = evidence["responses"]["control_plane_readiness"]["body"]
        assert readiness["status"] == "degraded"
    else:
        observations = evidence["responses"]["services"]["body"]["services"]
        assert any(not item["alive"] or item["ready"] is False for item in observations)
    # The evidence plane itself must recover after any affected dependency returns.
    deadline = time.monotonic() + 60
    with httpx.Client(base_url=live_executor.control_plane_url, timeout=10) as client:
        while True:
            response = client.get("/ready")
            if response.status_code == 200 and response.json()["status"] == "ready":
                break
            assert time.monotonic() < deadline, response.text
            time.sleep(1)
