import base64
import logging
from typing import Any
import httpx
from app.core.config import get_settings
from app.providers.tts.base import BaseTTSProvider, TTSProviderError, VoiceInfo

logger = logging.getLogger(__name__)
settings = get_settings()


class SarvamTTSProvider(BaseTTSProvider):
    """Sarvam AI Bulbul TTS Provider specialized for Indian languages (Hindi, Hinglish, English)."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.SARVAM_API_KEY
        self.base_url = "https://api.sarvam.ai/text-to-speech"

    @property
    def provider_id(self) -> str:
        return "sarvam"

    @property
    def model_version(self) -> str:
        return "bulbul:v1"

    async def get_supported_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                voice_id="sarvam_m_arvind",
                name="Arvind",
                provider="sarvam",
                gender="male",
                languages=["hi-IN", "en-IN"],
                vocal_archetype="warm baritone, authoritative narrator",
                supported_emotions=["neutral", "calm", "dramatic"],
            ),
            VoiceInfo(
                voice_id="sarvam_f_meera",
                name="Meera",
                provider="sarvam",
                gender="female",
                languages=["hi-IN", "en-IN"],
                vocal_archetype="expressive melodic female, clear urban tone",
                supported_emotions=["neutral", "excited", "whispered"],
            ),
            VoiceInfo(
                voice_id="sarvam_m_amartya",
                name="Amartya",
                provider="sarvam",
                gender="male",
                languages=["hi-IN", "en-IN"],
                vocal_archetype="young energetic urban male",
                supported_emotions=["neutral", "agitated", "casual"],
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
                "SARVAM_API_KEY is not configured.",
                "MissingAPIKey",
            )

        # Normalize speaker voice name
        speaker_name = voice_id.replace("sarvam_m_", "").replace("sarvam_f_", "").replace("sarvam_", "")
        if speaker_name not in ("arvind", "meera", "amartya", "pavithra", "maitreyi"):
            speaker_name = "arvind"

        # Determine language code: Hindi default, or English if detected
        target_language_code = "hi-IN"

        payload: dict[str, Any] = {
            "inputs": [text],
            "target_language_code": target_language_code,
            "speaker": speaker_name,
            "pitch": pitch,
            "pace": max(0.5, min(2.0, speed)),
            "loudness": 1.0,
            "speech_sample_rate": 24000,
            "enable_preprocessing": True,
            "model": self.model_version,
        }

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.base_url, headers=headers, json=payload)

            if response.status_code != 200:
                raise TTSProviderError(
                    self.provider_id,
                    line_id,
                    f"HTTP {response.status_code}: {response.text}",
                    f"HTTP_{response.status_code}",
                )

            res_data = response.json()
            audios = res_data.get("audios", [])
            if not audios:
                raise TTSProviderError(
                    self.provider_id,
                    line_id,
                    "No audio payload in Sarvam response.",
                    "EmptyAudiosList",
                )

            audio_bytes = base64.b64decode(audios[0])
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

