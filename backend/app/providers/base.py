from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class ProviderUsageMetadata:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""
    provider: str = ""
    usage_type: str = "ACTUAL"  # ACTUAL, ESTIMATED, or MOCK
    call_count: int = 1


class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM providers."""

    def __init__(self) -> None:
        self.last_usage: ProviderUsageMetadata | None = None
        self.usage_history: list[ProviderUsageMetadata] = []

    def record_usage(self, usage: ProviderUsageMetadata) -> None:
        """Record usage from an individual provider invocation."""
        self.last_usage = usage
        self.usage_history.append(usage)

    def get_last_usage(self) -> ProviderUsageMetadata | None:
        """Retrieve usage metadata from the most recent generation if available."""
        return self.last_usage

    def get_aggregated_usage(self) -> ProviderUsageMetadata:
        """Aggregate token counts, latency, and call counts across all recorded invocations."""
        if not self.usage_history:
            return ProviderUsageMetadata(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=0.0,
                model="",
                provider="",
                usage_type="ESTIMATED",
                call_count=0,
            )
        p_tokens = sum(u.prompt_tokens for u in self.usage_history)
        c_tokens = sum(u.completion_tokens for u in self.usage_history)
        tot_tokens = sum(u.total_tokens for u in self.usage_history)
        tot_lat = sum(u.latency_ms for u in self.usage_history)
        has_mock = any(u.usage_type == "MOCK" for u in self.usage_history)
        has_estimated = any(u.usage_type == "ESTIMATED" for u in self.usage_history)
        agg_type = "MOCK" if has_mock else ("ESTIMATED" if has_estimated else "ACTUAL")

        return ProviderUsageMetadata(
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            total_tokens=tot_tokens,
            latency_ms=tot_lat,
            model=self.usage_history[-1].model,
            provider=self.usage_history[-1].provider,
            usage_type=agg_type,
            call_count=len(self.usage_history),
        )

    def reset_usage(self) -> None:
        """Reset accumulated usage history."""
        self.usage_history.clear()
        self.last_usage = None

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        """Generate a response strictly validated against a Pydantic schema.

        Raises:
            LLMProviderError: On upstream network, auth, or rate limit failure.
            SchemaValidationError: When LLM response fails validation against the requested schema.
        """
        pass

    @abstractmethod
    async def generate_chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Generate standard freeform chat response.

        Raises:
            LLMProviderError: On upstream network, auth, or rate limit failure.
        """
        pass

