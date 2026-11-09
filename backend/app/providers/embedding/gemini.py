import logging
from typing import Any
import httpx
from app.core.config import get_settings
from app.core.exceptions import KathaException
from app.providers.embedding.base import BaseEmbeddingProvider

logger = logging.getLogger(__name__)
settings = get_settings()


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini text-embedding-004 multilingual embedding provider."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = "text-embedding-004"
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def dimension(self) -> int:
        return 768

    async def embed_text(self, text: str) -> list[float]:
        if not self.api_key:
            raise KathaException(
                detail="GEMINI_API_KEY is not configured for text embedding.",
                status_code=500,
                error_code="MISSING_EMBEDDING_API_KEY",
            )

        url = f"{self.base_url}/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, json=payload)
            if res.status_code != 200:
                raise KathaException(
                    detail=f"Gemini embedding API error: {res.text}",
                    status_code=502,
                    error_code="EMBEDDING_API_ERROR",
                )
            data = res.json()
            return data["embedding"]["values"]
        except Exception as exc:
            if isinstance(exc, KathaException):
                raise
            raise KathaException(
                detail=f"Failed to generate embedding: {exc}",
                status_code=502,
                error_code="EMBEDDING_GENERATION_FAILED",
            ) from exc

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Execute embeddings sequentially or concurrently
        return [await self.embed_text(t) for t in texts]
