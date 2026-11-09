import logging
from typing import Any
import httpx
from app.core.config import get_settings
from app.providers.tts.base import BaseTTSProvider, TTSProviderError, VoiceInfo

logger = logging.getLogger(__name__)
settings = get_settings()


class ElevenLabsTTSProvider(BaseTTSProvider):
    """ElevenLabs Multilingual v2 TTS Provider."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.ELEVENLABS_API_KEY
        self.base_url = "https://api.elevenlabs.io/v1/text-to-speech"

    @property
    def provider_id(self) -> str:
        return "elevenlabs"

    @property
    def model_version(self) -> str:
        return "eleven_multilingual_v2"

    async def get_supported_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                voice_id="21m00Tcm4TlvDq8ikWAM",
                name="Rachel",
                provider="elevenlabs",
                gender="female",
                languages=["en", "hi"],
                vocal_archetype="calm narrative female",
                supported_emotions=["neutral", "calm", "whispered"],
            ),
            VoiceInfo(
                voice_id="ErXwobaYiN019PkySvjV",
                name="Antoni",
                provider="elevenlabs",
                gender="male",
                languages=["en", "hi"],
                vocal_archetype="assertive dramatic male",
                supported_emotions=["neutral", "dramatic", "urgent"],
            ),
        ]

    async def synthesize_line(
        self,
        text: str,
        voice_id: str,
        line_id: str = "unknown",
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: str = "neutral",
    ) -> bytes:
        if not self.api_key:
            raise TTSProviderError(
                self.provider_id,
                line_id,
                "ELEVENLABS_API_KEY is not configured.",
                "MissingAPIKey",
            )

        # Default fallback voice ID if synthetic name is passed
        actual_voice_id = voice_id if len(voice_id) > 15 else "21m00Tcm4TlvDq8ikWAM"
        url = f"{self.base_url}/{actual_voice_id}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        # Emotion-aware style adjustment
        style_val = 0.4 if emotion in ("furious", "agitated", "haunting", "tearful") else 0.1

        payload: dict[str, Any] = {
            "text": text,
            "model_id": self.model_version,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "style": style_val,
                "use_speaker_boost": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)

            if response.status_code != 200:
                raise TTSProviderError(
                    self.provider_id,
                    line_id,
                    f"HTTP {response.status_code}: {response.text}",
                    f"HTTP_{response.status_code}",
                )

            audio_bytes = response.content
            if len(audio_bytes) < 100:
                raise TTSProviderError(
                    self.provider_id,
                    line_id,
                    f"Synthesized audio length ({len(audio_bytes)} bytes) is below minimum valid threshold (>100).",
                    "TruncatedAudio",
                )

            return audio_bytes

        except httpx.TimeoutException as exc:
            raise TTSProviderError(self.provider_id, line_id, f"Synthesis request timed out: {exc}", "Timeout") from exc
        except httpx.RequestError as exc:
            raise TTSProviderError(self.provider_id, line_id, f"Network error during synthesis: {exc}", "NetworkError") from exc
        except Exception as exc:
            if isinstance(exc, TTSProviderError):
                raise
            raise TTSProviderError(self.provider_id, line_id, f"Unexpected synthesis error: {exc}", type(exc).__name__) from exc

