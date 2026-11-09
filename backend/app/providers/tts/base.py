from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict, Field
from app.core.exceptions import KathaException


class VoiceInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    voice_id: str
    name: str
    provider: str
    gender: str
    languages: list[str]
    vocal_archetype: str
    supported_emotions: list[str] = Field(default_factory=list)


class TTSProviderError(KathaException):
    """Raised when text-to-speech synthesis fails."""

    def __init__(self, provider: str, line_id: str, detail: str, original_error: str | None = None) -> None:
        super().__init__(
            detail=f"TTS Provider [{provider}] failed for line '{line_id}': {detail}",
            status_code=502,
            title="TTS Provider Error",
            error_code="TTS_PROVIDER_ERROR",
            extras={"provider": provider, "line_id": line_id, "original_error": original_error},
        )


class BaseTTSProvider(ABC):
    """Abstract Base Class for Text-to-Speech synthesis providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier (e.g., 'mock', 'sarvam', 'elevenlabs')."""
        pass

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Active model version for cache key tracking."""
        pass

    @abstractmethod
    async def synthesize_line(
        self,
        text: str,
        voice_id: str,
        line_id: str = "unknown",
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: str = "neutral",
    ) -> bytes:
        """Synthesize spoken audio for a single dialogue line.

        Returns:
            bytes: Valid audio container bytes (WAV or MP3) with minimum size > 100 bytes.

        Raises:
            TTSProviderError: On upstream failure, network timeout, or invalid audio output.
        """
        pass

    @abstractmethod
    async def get_supported_voices(self) -> list[VoiceInfo]:
        """Return catalog of available voices with language and gender metadata."""
        pass

