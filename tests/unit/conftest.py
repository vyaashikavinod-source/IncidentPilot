import os

import pytest


@pytest.fixture(autouse=True)
def isolate_service_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("INCIDENTPILOT_"):
            monkeypatch.delenv(key)
