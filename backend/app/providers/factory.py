"""Provider and Model Factory for AditStudio LLM generation and evaluation."""

import logging
from typing import Literal
from app.core.config import get_settings
from app.core.exceptions import LLMProviderError
from app.providers.base import BaseLLMProvider
from app.providers.mock import MockLLMProvider

logger = logging.getLogger(__name__)
settings = get_settings()


def get_llm_provider(
    provider_name: str = "gemini",
    model_name: str | None = None,
    mode: Literal["MOCK", "LIVE"] = "LIVE",
) -> BaseLLMProvider:
    """Instantiate and return a configured LLM provider.

    In LIVE mode:
      - Validates API key presence and raises clear LLMProviderError on missing credentials.
      - Never silently falls back to a mock in LIVE mode.
    In MOCK mode:
      - Returns MockLLMProvider explicitly tagged for deterministic mock testing.
    """
    mode_normalized = mode.upper()
    provider_key = (provider_name or "mock").lower()

    if mode_normalized == "MOCK":
        return MockLLMProvider(model_name=model_name or "mock-model")

    if mode_normalized != "LIVE":
        raise ValueError(f"Invalid provider factory mode: '{mode}'. Must be 'MOCK' or 'LIVE'.")

    if provider_key in ("mock", "mock-model"):
        raise ValueError("Cannot use 'mock' provider in LIVE mode. Use mode='MOCK' for deterministic tests.")

    if provider_key == "gemini":
        if not settings.GEMINI_API_KEY:
            raise LLMProviderError(
                "gemini",
                "GEMINI_API_KEY is not configured for LIVE execution.",
                "MissingAPIKey",
            )
        from app.providers.gemini import GeminiProvider

        return GeminiProvider(model=model_name or "gemini-1.5-pro")

    if provider_key == "groq":
        if not settings.GROQ_API_KEY:
            raise LLMProviderError(
                "groq",
                "GROQ_API_KEY is not configured for LIVE execution.",
                "MissingAPIKey",
            )
        from app.providers.groq import GroqProvider

        return GroqProvider(model=model_name or "llama-3.3-70b-versatile")

    raise LLMProviderError(
        provider_name,
        f"Unsupported provider '{provider_name}' in LIVE mode.",
        "UnsupportedProvider",
    )
