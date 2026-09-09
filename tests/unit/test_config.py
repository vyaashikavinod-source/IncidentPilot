import pytest
from pydantic import ValidationError

from incidentpilot.shared.config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ENVIRONMENT", "SERVICE_NAME", "LOG_LEVEL"):
        monkeypatch.delenv(f"INCIDENTPILOT_{name}", raising=False)


def test_safe_defaults() -> None:
    settings = Settings()
    assert settings.environment == "local"
    assert settings.service_name == "incidentpilot"
    assert settings.log_level == "INFO"


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENTPILOT_SERVICE_NAME", "auth")
    monkeypatch.setenv("INCIDENTPILOT_ENVIRONMENT", "test")
    monkeypatch.setenv("INCIDENTPILOT_LOG_LEVEL", "DEBUG")
    assert Settings().model_dump() == {
        "environment": "test",
        "service_name": "auth",
        "log_level": "DEBUG",
        "telemetry_enabled": False,
        "otlp_endpoint": "http://localhost:4318",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [("ENVIRONMENT", "production"), ("SERVICE_NAME", "bad name"), ("LOG_LEVEL", "TRACE")],
)
def test_invalid_environment_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(f"INCIDENTPILOT_{name}", value)
    with pytest.raises(ValidationError):
        Settings()
