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
    usage_type: str = "ACTUAL"  # ACTUAL or ESTIMATED


class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM providers."""

    def __init__(self) -> None:
        self.last_usage: ProviderUsageMetadata | None = None

    def get_last_usage(self) -> ProviderUsageMetadata | None:
        """Retrieve actual usage metadata from the most recent generation if available."""
        return self.last_usage

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

