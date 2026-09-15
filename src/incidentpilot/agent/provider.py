from collections.abc import Sequence
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from incidentpilot.incidents.models import Diagnosis, EvidenceAction


class ProviderError(RuntimeError):
    pass


class ProviderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis: str = Field(min_length=1, max_length=1000)
    observation: str = Field(min_length=1, max_length=2000)
    disposition: str = Field(pattern="^(supported|weakened|rejected|unresolved)$")
    action: EvidenceAction | None = None
    diagnosis: Diagnosis | None = None
    remediation: dict[str, str] | None = None
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
            raise ProviderError("fake provider exhausted") from exc


class OpenAIProvider:
    """Fixed-endpoint provider; the agent cannot supply URLs or arbitrary HTTP requests."""

    name = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self, api_key: str, model: str, timeout: float, max_output_tokens: int, temperature: float
    ) -> None:
        if not api_key:
            raise ProviderError("OpenAI provider requires a configured API key")
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
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ProviderError("LLM request failed or returned malformed output") from exc
