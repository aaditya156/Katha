from abc import ABC, abstractmethod
from typing import TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM providers."""

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
