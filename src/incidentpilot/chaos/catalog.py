"""Scenario loading with explicit public/private separation."""

import hashlib
import json
from pathlib import Path

from incidentpilot.chaos.models import GroundTruth, Scenario

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "chaos" / "scenarios"
GROUND_TRUTH = ROOT / "chaos" / "ground_truth"


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_scenarios(directory: Path = SCENARIOS) -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}
    for path in sorted(directory.glob("*.json")):
        scenario = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        if scenario.scenario_id in scenarios:
            raise ValueError(f"duplicate scenario ID: {scenario.scenario_id}")
        scenarios[scenario.scenario_id] = scenario
    if not scenarios:
        raise ValueError("scenario catalog is empty")
    return scenarios


def load_ground_truth(scenario: Scenario, directory: Path = GROUND_TRUTH) -> GroundTruth:
    path = directory / f"{scenario.scenario_id}.json"
    truth = GroundTruth.model_validate_json(path.read_text(encoding="utf-8"))
    if (truth.scenario_id, truth.scenario_version) != (scenario.scenario_id, scenario.version):
        raise ValueError("ground truth does not match scenario identity/version")
    if (truth.affected_service, truth.failure_class) != (
        scenario.affected_service,
        scenario.failure_class,
    ):
        raise ValueError("ground truth classification does not match public metadata")
    return truth


def stable_json(model: Scenario | GroundTruth) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
