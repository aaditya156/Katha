import hashlib
import math
import re
from app.providers.embedding.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, normalized 768-dimensional embedding provider for testing semantic retrieval."""

    def __init__(self, dimension: int = 768) -> None:
        self._dim = dimension

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def dimension(self) -> int:
        return self._dim

    def _generate_vector(self, text: str) -> list[float]:
        words = re.findall(r"\w+", text.lower())
        vec = [0.0] * self._dim

        if not words:
            vec[0] = 1.0
            return vec

        for word in words:
            # Map word to deterministic bucket
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx1 = h % self._dim
            idx2 = (h >> 16) % self._dim
            idx3 = (h >> 32) % self._dim
            vec[idx1] += 2.0
            vec[idx2] += 1.5
            vec[idx3] += 1.0

        # Calculate L2 norm and normalize to unit vector
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0

        return vec

    async def embed_text(self, text: str) -> list[float]:
        return self._generate_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_vector(t) for t in texts]
