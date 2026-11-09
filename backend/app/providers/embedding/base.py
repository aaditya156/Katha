from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """Abstract Base Class for text embedding models."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Provider identifier (e.g., 'mock', 'gemini')."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output embedding vector dimensionality (e.g., 768)."""
        pass

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate normalized embedding vector for a single text string."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized embedding vectors for a batch of text strings."""
        pass
