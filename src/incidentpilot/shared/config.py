"""Validated configuration; no implicit file reads or credentials."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Common service settings loaded on construction, never on import."""

    model_config = SettingsConfigDict(
        env_prefix="INCIDENTPILOT_", extra="forbid", hide_input_in_errors=True
    )

    environment: Literal["local", "test", "production"] = "local"
    service_name: str = Field(default="incidentpilot", pattern=r"^[a-z][a-z0-9_-]{0,62}$")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    telemetry_enabled: bool = False
    otlp_endpoint: str = "http://localhost:4318"

    @field_validator("otlp_endpoint")
    @classmethod
    def validate_otlp_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("otlp_endpoint must be an HTTP(S) URL without credentials")
        return value.rstrip("/")


class HTTPSettings(Settings):
    http_timeout: float = Field(default=3.0, gt=0, le=30)


class AuthSettings(Settings):
    sandbox_auth_token: SecretStr = Field(min_length=16)


class DataSettings(Settings):
    database_url: SecretStr
    internal_token: SecretStr = Field(min_length=16)
    incident_token: SecretStr = Field(min_length=16)
    audit_signing_secret: SecretStr = Field(min_length=32)
    investigation_lease_seconds: int = Field(default=600, ge=300, le=3600)

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


class ControlPlaneSettings(HTTPSettings):
    prometheus_url: str = "http://prometheus:9090"
    loki_url: str = "http://loki:3100"
    tempo_url: str = "http://tempo:3200"
    data_url: str = "http://data:8000"
    gateway_url: str = "http://gateway:8000"
    auth_url: str = "http://auth:8000"
    worker_metrics_url: str = "http://worker:9100"
    internal_token: SecretStr = Field(min_length=16)
    evidence_max_window_seconds: int = Field(default=86400, ge=60, le=86400)
    evidence_max_results: int = Field(default=500, ge=1, le=1000)

    @field_validator(
        "prometheus_url",
        "loki_url",
        "tempo_url",
        "data_url",
        "gateway_url",
        "auth_url",
        "worker_metrics_url",
    )
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return ClientSettings.http_url(value)


class AgentSettings(HTTPSettings):
    data_url: str = "http://data:8000"
    evidence_url: str = "http://control-plane:8000"
    data_token: SecretStr = Field(min_length=16)
    operator_signing_secret: SecretStr = Field(min_length=32)
    operator_token_issuer: str = "incidentpilot-local"
    operator_token_audience: str = "incidentpilot-operator-api"
    llm_provider: Literal["openai", "fake"] = "fake"
    llm_model: str = Field(default="gpt-5-mini", min_length=1, max_length=100)
    llm_api_key: SecretStr | None = None
    llm_timeout: float = Field(default=20, gt=0, le=60)
    llm_max_output_tokens: int = Field(default=1200, ge=100, le=4000)
    investigation_max_provider_calls: int = Field(default=6, ge=1, le=12)
    investigation_max_input_tokens: int = Field(default=12_000, ge=100, le=100_000)
    investigation_max_total_tokens: int = Field(default=16_000, ge=100, le=100_000)
    investigation_max_cost_usd: float | None = Field(default=None, gt=0, le=100)
    investigation_context_bytes: int = Field(default=120_000, ge=10_000, le=500_000)
    provider_retry_limit: int = Field(default=1, ge=0, le=3)
    provider_retry_backoff_seconds: float = Field(default=0.1, ge=0, le=5)
    llm_input_cost_per_million: float | None = Field(default=None, ge=0)
    llm_output_cost_per_million: float | None = Field(default=None, ge=0)
    llm_pricing_currency: str = Field(default="USD", min_length=3, max_length=3)
    llm_pricing_source_version: str | None = Field(default=None, max_length=100)
    investigation_max_evidence_items: int = Field(default=50, ge=1, le=200)
    investigation_max_memory_items: int = Field(default=5, ge=0, le=10)
    investigation_max_evidence_payload_bytes: int = Field(default=25_000, ge=1000, le=100_000)
    investigation_max_turns: int = Field(default=6, ge=1, le=12)
    investigation_max_tool_calls: int = Field(default=8, ge=1, le=20)
    investigation_max_seconds: int = Field(default=90, ge=10, le=300)
    investigation_max_evidence_bytes: int = Field(default=100_000, ge=10_000, le=500_000)
    llm_temperature: float = Field(default=0, ge=0, le=1)
    operator_console_origin: str | None = None

    @field_validator("operator_console_origin")
    @classmethod
    def validate_operator_console_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "operator_console_origin must be an HTTP(S) origin without credentials"
            )
        return value.rstrip("/")

    @field_validator("data_url", "evidence_url")
    @classmethod
    def validate_agent_url(cls, value: str, info: ValidationInfo) -> str:
        normalized = ClientSettings.http_url(value)
        parsed = urlsplit(normalized)
        if parsed.scheme != "http" or parsed.port != 8000 or parsed.path not in {"", "/"}:
            raise ValueError("agent service URLs must use the internal HTTP service port")
        expected = (
            {"data", "data.railway.internal"}
            if info.field_name == "data_url"
            else {"control-plane", "control-plane.railway.internal"}
        )
        if parsed.hostname not in expected:
            raise ValueError("agent service URL host is not allowlisted")
        return normalized
