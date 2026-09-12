import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def isolate_service_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("INCIDENTPILOT_"):
            monkeypatch.delenv(key)


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Workspace-local temp path for the restricted Windows test environment."""
    path = Path(__file__).resolve().parents[2] / ".test-tmp" / str(uuid4())
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)
