"""Explicit operator CLI with no arbitrary command or target inputs."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from incidentpilot.chaos.catalog import ROOT, load_scenarios
from incidentpilot.chaos.executor import RunExecutor


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m incidentpilot.chaos")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("scenario_id")
    run = commands.add_parser("run")
    run.add_argument("scenario_id")
    recover = commands.add_parser("recover")
    recover.add_argument("run_id", type=UUID)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    scenarios = load_scenarios()
    if args.command == "list":
        for scenario_id in scenarios:
            print(scenario_id)
        return 0
    if args.command == "inspect":
        scenario = scenarios.get(args.scenario_id)
        if scenario is None:
            raise SystemExit("unknown scenario ID")
        print(json.dumps(scenario.model_dump(mode="json"), sort_keys=True, indent=2))
        return 0
    executor = RunExecutor(
        ROOT,
        os.getenv("INCIDENTPILOT_CONTROL_PLANE_URL", "http://127.0.0.1:8001"),
        Path(os.getenv("INCIDENTPILOT_CHAOS_RUNS_DIR", ROOT / "evaluation" / "runs")),
    )
    if args.command == "run":
        scenario = scenarios.get(args.scenario_id)
        if scenario is None:
            raise SystemExit("unknown scenario ID")
        print(executor.run(scenario).model_dump_json(indent=2))
        return 0
    print(executor.recover(args.run_id, scenarios).model_dump_json(indent=2))
    return 0
