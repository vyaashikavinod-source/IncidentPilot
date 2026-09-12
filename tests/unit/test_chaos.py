import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from incidentpilot.chaos.catalog import (
    GROUND_TRUTH,
    SCENARIOS,
    checksum,
    load_ground_truth,
    load_scenarios,
    stable_json,
)
from incidentpilot.chaos.cli import main
from incidentpilot.chaos.executor import RunExecutor
from incidentpilot.chaos.injector import ComposeInjector
from incidentpilot.chaos.models import RunManifest, Scenario


def test_catalog_has_nine_unique_valid_scenarios_and_matching_truth() -> None:
    scenarios = load_scenarios()
    assert len(scenarios) == 9
    assert len(set(scenarios)) == 9
    for scenario in scenarios.values():
        truth = load_ground_truth(scenario)
        assert truth.scenario_id == scenario.scenario_id
        assert truth.scenario_version == scenario.version
        assert 10 <= scenario.maximum_duration_seconds <= 300
        assert "ground_truth_root_cause" not in stable_json(scenario)


def test_scenario_rejects_unknown_fields_bad_ids_and_unbounded_duration() -> None:
    payload = json.loads((SCENARIOS / "worker-stopped.json").read_text())
    for key, value in (
        ("scenario_id", "../unsafe"),
        ("maximum_duration_seconds", 301),
        ("affected_service", "arbitrary-container"),
        ("injection_method", "shell"),
    ):
        invalid = {**payload, key: value}
        with pytest.raises(ValidationError):
            Scenario.model_validate(invalid)
    with pytest.raises(ValidationError):
        Scenario.model_validate({**payload, "command": "anything"})


def test_duplicate_scenario_ids_are_rejected(tmp_path: Path) -> None:
    source = SCENARIOS / "worker-stopped.json"
    (tmp_path / "one.json").write_bytes(source.read_bytes())
    (tmp_path / "two.json").write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="duplicate"):
        load_scenarios(tmp_path)


def test_ground_truth_must_match_public_identity(tmp_path: Path) -> None:
    scenario = load_scenarios()["worker-stopped"]
    payload = json.loads((GROUND_TRUTH / "worker-stopped.json").read_text())
    payload["scenario_version"] = "2.0.0"
    (tmp_path / "worker-stopped.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="identity"):
        load_ground_truth(scenario, tmp_path)


def test_checksum_changes_with_content(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text("one")
    first = checksum(path)
    path.write_text("two")
    assert checksum(path) != first


def test_manifest_integrity_and_timestamp_ordering() -> None:
    now = datetime.now(UTC)
    manifest = RunManifest(
        run_id=uuid4(),
        scenario_id="worker-stopped",
        scenario_version="1.0.0",
        repository_commit="a" * 40,
        started_at=now,
        affected_service="worker",
        sandbox_versions={"compose": "test"},
        evidence_window_start=now,
        ground_truth_reference="chaos/ground_truth/worker-stopped.json",
        scenario_checksum_sha256="a" * 64,
        ground_truth_checksum_sha256="b" * 64,
    )
    assert RunManifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValidationError):
        RunManifest.model_validate(
            {**manifest.model_dump(), "injection_timestamp": now - timedelta(seconds=1)}
        )


def test_injector_only_allows_fixed_verbs_and_targets(tmp_path: Path) -> None:
    injector = ComposeInjector(tmp_path)
    with pytest.raises(ValueError, match="allowlisted"):
        injector._compose("exec", "worker")
    with pytest.raises(ValueError, match="allowlisted"):
        injector._compose("stop", "arbitrary")


def test_cli_lists_and_inspects_only_public_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    assert "worker-stopped" in capsys.readouterr().out
    assert main(["inspect", "worker-stopped"]) == 0
    output = capsys.readouterr().out
    assert "expected_observable_signals" in output
    assert "ground_truth_root_cause" not in output
    with pytest.raises(SystemExit, match="unknown"):
        main(["inspect", "not-allowlisted"])


def test_executor_recovers_after_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = load_scenarios()["worker-stopped"]
    executor = RunExecutor(Path(__file__).resolve().parents[2], "http://evidence", tmp_path)
    executor.injector = Mock()
    executor.injector.verify_active.return_value = True
    executor.injector.verify_recovered.return_value = True
    monkeypatch.setattr(executor, "_commit", Mock(return_value="a" * 40))
    monkeypatch.setattr(executor, "_versions", Mock(return_value={"images": "digest"}))
    monkeypatch.setattr(
        "incidentpilot.chaos.executor.capture_evidence", Mock(side_effect=RuntimeError("capture"))
    )
    with pytest.raises(RuntimeError, match="capture"):
        executor.run(scenario)
    executor.injector.recover.assert_called_once_with(scenario)
    manifest_path = next(tmp_path.glob("*/manifest.json"))
    manifest = RunManifest.model_validate_json(manifest_path.read_text())
    assert manifest.injection_result == "succeeded"
    assert manifest.recovery_result == "succeeded"
    assert not executor.active_path.exists()
