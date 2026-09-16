from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from incidentpilot.incidents.models import Diagnosis, EvidenceAction


class RemediationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposed_action_type: Literal[
        "restart_service",
        "rollback_deployment",
        "restore_dependency",
        "scale_worker",
        "configuration_change",
        "investigate_manually",
    ]
    target_service: str = Field(min_length=1, max_length=63)
    description: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
    expected_effect: str = Field(min_length=1, max_length=1000)
    risk: str = Field(min_length=1, max_length=1000)
    rollback_plan: str = Field(min_length=1, max_length=1000)
    verification_plan: str = Field(min_length=1, max_length=1000)


class ProviderErrorCategory(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_RESPONSE = "invalid_response"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    CONTEXT_LIMIT_EXCEEDED = "context_limit_exceeded"
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


class ProviderError(RuntimeError):
    def __init__(
        self, category: ProviderErrorCategory = ProviderErrorCategory.UNKNOWN_PROVIDER_ERROR
    ) -> None:
        super().__init__(f"LLM request failed: {category.value}")
        self.category = category

    @property
    def retryable(self) -> bool:
        return self.category in {
            ProviderErrorCategory.TIMEOUT,
            ProviderErrorCategory.RATE_LIMITED,
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        }


class ProviderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis: str = Field(min_length=1, max_length=1000)
    observation: str = Field(min_length=1, max_length=2000)
    disposition: str = Field(pattern="^(supported|weakened|rejected|unresolved)$")
    action: EvidenceAction | None = None
    diagnosis: Diagnosis | None = None
    remediation: RemediationDraft | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class LLMProvider(Protocol):
    name: str
    model: str

    def decide(self, system_policy: str, investigation_data: str) -> ProviderDecision: ...


class FakeProvider:
    name = "fake"
    model = "deterministic-test"

    def __init__(self, decisions: Sequence[ProviderDecision]) -> None:
        self.decisions = iter(decisions)

    def decide(self, system_policy: str, investigation_data: str) -> ProviderDecision:
        try:
            return next(self.decisions)
        except StopIteration as exc:
            raise ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE) from exc


class OpenAIProvider:
    """Fixed-endpoint provider; the agent cannot supply URLs or arbitrary HTTP requests."""

    name = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self, api_key: str, model: str, timeout: float, max_output_tokens: int, temperature: float
    ) -> None:
        if not api_key:
            raise ProviderError(ProviderErrorCategory.AUTHENTICATION_FAILED)
        self.model, self.timeout = model, timeout
        self.api_key, self.max_output_tokens, self.temperature = (
            api_key,
            max_output_tokens,
            temperature,
        )

    def decide(self, system_policy: str, investigation_data: str) -> ProviderDecision:
        try:
            request: dict[str, object] = {
                "model": self.model,
                "instructions": system_policy,
                "input": investigation_data,
                "max_output_tokens": self.max_output_tokens,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "incidentpilot_decision",
                        "strict": True,
                        "schema": ProviderDecision.model_json_schema(),
                    }
                },
            }
            if self.temperature:
                request["temperature"] = self.temperature
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request,
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
            text = body["output"][0]["content"][0]["text"]
            decision = ProviderDecision.model_validate_json(text)
            usage = body.get("usage", {})
            return decision.model_copy(
                update={
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorCategory.TIMEOUT) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            category = (
                ProviderErrorCategory.AUTHENTICATION_FAILED
                if status in {401, 403}
                else ProviderErrorCategory.RATE_LIMITED
                if status == 429
                else ProviderErrorCategory.PROVIDER_UNAVAILABLE
            )
            raise ProviderError(category) from exc
        except ValidationError as exc:
            raise ProviderError(ProviderErrorCategory.SCHEMA_VALIDATION_FAILED) from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(ProviderErrorCategory.INVALID_RESPONSE) from exc
