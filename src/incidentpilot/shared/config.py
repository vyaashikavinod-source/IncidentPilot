"""Validated configuration; no implicit file reads or credentials."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Common service settings loaded on construction, never on import."""

    model_config = SettingsConfigDict(
        env_prefix="INCIDENTPILOT_", extra="forbid", hide_input_in_errors=True
    )

    environment: Literal["local", "test"] = "local"
    service_name: str = Field(default="incidentpilot", pattern=r"^[a-z][a-z0-9_-]{0,62}$")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class HTTPSettings(Settings):
    http_timeout: float = Field(default=3.0, gt=0, le=30)


class AuthSettings(Settings):
    sandbox_auth_token: SecretStr = Field(min_length=16)


class DataSettings(Settings):
    database_url: SecretStr
    internal_token: SecretStr = Field(min_length=16)

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        parsed = urlsplit(value.get_secret_value())
        if (
            parsed.scheme != "postgresql+psycopg"
            or not parsed.hostname
            or not parsed.username
            or len(parsed.path) < 2
        ):
            raise ValueError(
                "database_url requires PostgreSQL psycopg scheme, host, user and database"
            )
        return value


class ClientSettings(HTTPSettings):
    data_url: str
    internal_token: SecretStr = Field(min_length=16)
    broker_url: SecretStr

    @field_validator("data_url", check_fields=False)
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("service URL must be an HTTP(S) URL without credentials or query")
        return value.rstrip("/")

    @field_validator("broker_url")
    @classmethod
    def redis_only(cls, value: SecretStr) -> SecretStr:
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("broker_url must be a Redis URL")
        return value


class GatewaySettings(ClientSettings):
    auth_url: str

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, value: str) -> str:
        return cls.http_url(value)


class WorkerSettings(ClientSettings):
    worker_retry_limit: int = Field(default=3, ge=0, le=5)
    worker_retry_delay: int = Field(default=2, ge=1, le=30)
