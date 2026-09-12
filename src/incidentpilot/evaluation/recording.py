import json
from pathlib import Path

from incidentpilot.evaluation.models import ManualDiagnosis


def record_manual_diagnosis(path: Path, diagnosis: ManualDiagnosis) -> None:
    """Write a manual diagnosis as stable JSON without private ground truth."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = diagnosis.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
