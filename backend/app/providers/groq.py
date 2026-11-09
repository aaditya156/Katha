import asyncio
import json
import logging
from typing import Any, TypeVar
import httpx
from pydantic import BaseModel, ValidationError
from app.core.config import get_settings
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)
settings = get_settings()
T = TypeVar("T", bound=BaseModel)


class GroqProvider(BaseLLMProvider):
    """Groq LLM provider with JSON mode structured generation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama-3.3-70b-versatile",
    ) -> None:
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    async def _request_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise LLMProviderError("groq", "GROQ_API_KEY is not configured.", "MissingAPIKey")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        max_retries = settings.LLM_MAX_RETRIES

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                    response = await client.post(self.base_url, headers=headers, json=payload)

                if response.status_code == 200:
                    return response.json()

                if response.status_code in (429, 503) and attempt < max_retries:
                    wait_time = 2**attempt
                    logger.warning(
                        f"Groq API rate limited/busy ({response.status_code}). Retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                raise LLMProviderError(
                    "groq",
                    f"HTTP {response.status_code}: {response.text}",
                    f"Status{response.status_code}",
                )

            except httpx.TimeoutException as exc:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                raise LLMProviderError("groq", f"Request timed out: {exc}", "Timeout") from exc
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                raise LLMProviderError("groq", f"Network error: {exc}", "NetworkError") from exc

        raise LLMProviderError("groq", "Max retries exceeded", "MaxRetriesExceeded")

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        system_instruction = (
            (system_prompt or "You are an expert audio story planner and writer.")
            + f"\n\nYou MUST respond ONLY with valid JSON conforming strictly to the following JSON schema:\n{schema_json}"
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }

        res_json = await self._request_with_retry(payload)

        try:
            raw_text = res_json["choices"][0]["message"]["content"]
            parsed_dict = json.loads(raw_text)
            return schema.model_validate(parsed_dict)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise SchemaValidationError(
                schema.__name__,
                str(res_json),
                f"Failed to extract JSON from Groq choice: {exc}",
            ) from exc
        except ValidationError as exc:
            raise SchemaValidationError(
                schema.__name__,
                raw_text if "raw_text" in locals() else str(res_json),
                str(exc),
            ) from exc

    async def generate_chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
        }

        res_json = await self._request_with_retry(payload)
        try:
            return res_json["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMProviderError("groq", f"Failed to parse text: {exc}") from exc
