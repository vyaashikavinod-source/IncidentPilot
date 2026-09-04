"""Validated configuration; no implicit file reads or credentials."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Common service settings loaded on construction, never on import."""

    model_config = SettingsConfigDict(env_prefix="INCIDENTPILOT_", extra="forbid")

    environment: Literal["local", "test"] = "local"
    service_name: str = Field(default="incidentpilot", pattern=r"^[a-z][a-z0-9_-]{0,62}$")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
