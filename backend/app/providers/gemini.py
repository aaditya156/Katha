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


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider with schema-enforced structured generation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    async def _request_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise LLMProviderError(
                "gemini",
                "GEMINI_API_KEY is not configured.",
                "MissingAPIKey",
            )

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        max_retries = settings.LLM_MAX_RETRIES

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                    response = await client.post(url, headers=headers, json=payload)

                if response.status_code == 200:
                    return response.json()

                if response.status_code in (429, 503) and attempt < max_retries:
                    wait_time = 2**attempt
                    logger.warning(
                        f"Gemini API rate limited/busy ({response.status_code}). Retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                raise LLMProviderError(
                    "gemini",
                    f"HTTP {response.status_code}: {response.text}",
                    f"Status{response.status_code}",
                )

            except httpx.TimeoutException as exc:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                raise LLMProviderError("gemini", f"Request timed out: {exc}", "Timeout") from exc
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                raise LLMProviderError("gemini", f"Network error: {exc}", "NetworkError") from exc

        raise LLMProviderError("gemini", "Max retries exceeded", "MaxRetriesExceeded")

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        schema_json = schema.model_json_schema()

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": schema_json,
                "temperature": 0.7,
            },
        }

        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        res_json = await self._request_with_retry(payload)

        try:
            candidates = res_json.get("candidates", [])
            if not candidates:
                raise LLMProviderError("gemini", "No candidates returned by Gemini API")

            raw_text = candidates[0]["content"]["parts"][0]["text"]
            parsed_dict = json.loads(raw_text)
            return schema.model_validate(parsed_dict)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise SchemaValidationError(
                schema.__name__,
                str(res_json),
                f"Failed to extract JSON from Gemini candidate: {exc}",
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
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        res_json = await self._request_with_retry(payload)
        try:
            return res_json["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:
            raise LLMProviderError("gemini", f"Failed to parse text: {exc}") from exc

