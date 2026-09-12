"""Narrow host-side Compose injector; targets and verbs are code allowlisted."""

import json
import subprocess
import time
from pathlib import Path

from incidentpilot.chaos.models import InjectionMethod, Scenario

ALLOWED_TARGETS = frozenset(
    {
        "postgres",
        "redis",
        "worker",
        "auth",
        "data",
        "gateway",
        "otel-collector",
        "prometheus",
        "tempo",
    }
)


class ComposeInjector:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _compose(self, verb: str, service: str) -> None:
        if verb not in {"stop", "start", "pause", "unpause"} or service not in ALLOWED_TARGETS:
            raise ValueError("operation is not allowlisted")
        subprocess.run(
            ["docker", "compose", verb, service],
            cwd=self.root,
            check=True,
            timeout=60,
            capture_output=True,
            text=True,
        )

    def inject(self, scenario: Scenario) -> None:
        verb = "stop" if scenario.injection_method == InjectionMethod.COMPOSE_STOP else "pause"
        self._compose(verb, scenario.affected_service)

    def verify_active(self, scenario: Scenario) -> bool:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            cwd=self.root,
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        )
        running = set(result.stdout.splitlines())
        if scenario.injection_method == InjectionMethod.COMPOSE_STOP:
            return scenario.affected_service not in running
        detail = subprocess.run(
            ["docker", "compose", "ps", "--format", "json", scenario.affected_service],
            cwd=self.root,
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        ).stdout
        return "paused" in detail.casefold()

    def recover(self, scenario: Scenario) -> None:
        verb = "start" if scenario.injection_method == InjectionMethod.COMPOSE_STOP else "unpause"
        self._compose(verb, scenario.affected_service)

    def verify_recovered(self, scenario: Scenario, timeout: int = 90) -> bool:
        deadline = time.monotonic() + min(timeout, scenario.maximum_duration_seconds)
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json", scenario.affected_service],
                cwd=self.root,
                check=True,
                timeout=30,
                capture_output=True,
                text=True,
            )
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            if rows and all(
                row.get("State") == "running" and row.get("Health", "") in {"", "healthy"}
                for row in rows
            ):
                return True
            time.sleep(1)
        return False
