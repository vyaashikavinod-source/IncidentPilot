"""Fail-safe execution, provenance, state, and evidence packaging."""

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from incidentpilot.chaos.catalog import GROUND_TRUTH, SCENARIOS, checksum, load_ground_truth
from incidentpilot.chaos.evidence import capture_evidence
from incidentpilot.chaos.injector import ComposeInjector
from incidentpilot.chaos.models import RunManifest, Scenario

ACTIVE_FILE = ".incidentpilot-chaos-active.json"


class RunExecutor:
    def __init__(self, root: Path, control_plane_url: str, runs_dir: Path) -> None:
        self.root = root
        self.control_plane_url = control_plane_url
        self.runs_dir = runs_dir
        self.injector = ComposeInjector(root)
        self.active_path = root / ACTIVE_FILE

    def _commit(self) -> str:
        return subprocess.run(
            ["git", "-c", f"safe.directory={self.root.as_posix()}", "rev-parse", "HEAD"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    def _versions(self) -> dict[str, str]:
        versions = subprocess.run(
            ["docker", "compose", "images", "--format", "json"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        rows = json.loads(versions)
        result = {
            f"image:{row['ContainerName']}": f"{row['Repository']}@{row['ID']}" for row in rows
        }
        result["compose_images_sha256"] = hashlib.sha256(versions.encode()).hexdigest()
        result["docker_compose"] = subprocess.run(
            ["docker", "compose", "version", "--short"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return result

    def _write(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def run(self, scenario: Scenario) -> RunManifest:
        if self.active_path.exists():
            raise RuntimeError("another chaos run is active; recover it first")
        run_id = uuid4()
        run_dir = self.runs_dir / str(run_id)
        truth_path = GROUND_TRUTH / f"{scenario.scenario_id}.json"
        scenario_path = SCENARIOS / f"{scenario.scenario_id}.json"
        load_ground_truth(scenario)
        now = datetime.now(UTC)
        deadline = time.monotonic() + scenario.maximum_duration_seconds
        manifest = RunManifest(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.version,
            repository_commit=self._commit(),
            started_at=now,
            affected_service=scenario.affected_service,
            sandbox_versions=self._versions(),
            evidence_window_start=now,
            ground_truth_reference=str(truth_path.relative_to(self.root)).replace("\\", "/"),
            scenario_checksum_sha256=checksum(scenario_path),
            ground_truth_checksum_sha256=checksum(truth_path),
        )
        self._write(run_dir / "manifest.json", manifest)
        self._write(self.active_path, {"run_id": str(run_id), "scenario_id": scenario.scenario_id})
        injected = False
        try:
            # Recovery is attempted even if Compose reports a partial injection failure.
            injected = True
            self.injector.inject(scenario)
            if not self.injector.verify_active(scenario):
                raise RuntimeError("injected fault was not observable")
            manifest.injection_timestamp = datetime.now(UTC)
            manifest.injection_result = "succeeded"
            manifest.scenario_status = "active"
            self._write(run_dir / "manifest.json", manifest)
            snapshot = capture_evidence(self.control_plane_url, scenario)
            self._write(run_dir / "evidence.json", snapshot)
            if time.monotonic() > deadline:
                raise TimeoutError("scenario exceeded its hard maximum duration")
        except Exception:
            if manifest.injection_result == "pending":
                manifest.injection_result = "failed"
            manifest.scenario_status = "failed"
            raise
        finally:
            if injected:
                try:
                    self.injector.recover(scenario)
                    if not self.injector.verify_recovered(scenario):
                        raise RuntimeError("service did not recover")
                    manifest.recovery_result = "succeeded"
                    manifest.scenario_status = "recovered"
                except Exception:
                    manifest.recovery_result = "failed"
                    manifest.scenario_status = "failed"
            manifest.recovery_timestamp = datetime.now(UTC)
            manifest.evidence_window_end = manifest.recovery_timestamp
            self._write(run_dir / "manifest.json", manifest)
            if manifest.recovery_result == "succeeded" and self.active_path.exists():
                self.active_path.unlink()
        return manifest

    def recover(self, run_id: UUID, scenarios: dict[str, Scenario]) -> RunManifest:
        path = self.runs_dir / str(run_id) / "manifest.json"
        manifest = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        scenario = scenarios[manifest.scenario_id]
        self.injector.recover(scenario)
        if not self.injector.verify_recovered(scenario):
            raise RuntimeError("service did not recover")
        manifest.recovery_result = "succeeded"
        manifest.scenario_status = "recovered"
        manifest.recovery_timestamp = datetime.now(UTC)
        manifest.evidence_window_end = manifest.recovery_timestamp
        self._write(path, manifest)
        if self.active_path.exists():
            self.active_path.unlink()
        return manifest
