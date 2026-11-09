import asyncio
import io
import math
import struct
from typing import Any
import wave
from app.providers.tts.base import BaseTTSProvider, TTSProviderError, VoiceInfo


class MockTTSProvider(BaseTTSProvider):
    """Deterministic Mock TTS Provider generating valid 24kHz PCM WAV audio for testing."""

    def __init__(self, mode: str = "normal", delay_seconds: float = 0.0) -> None:
        self.mode = mode
        self.delay_seconds = delay_seconds
        self.sample_rate = 24000
        self.synthesis_calls: list[dict[str, Any]] = []

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def model_version(self) -> str:
        return "mock-v1"

    async def get_supported_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                voice_id="mock_m_kabir",
                name="Kabir",
                provider="mock",
                gender="male",
                languages=["hi", "en", "hinglish"],
                vocal_archetype="warm baritone",
                supported_emotions=["neutral", "calm", "curious", "whispered"],
            ),
            VoiceInfo(
                voice_id="mock_f_ananya",
                name="Ananya",
                provider="mock",
                gender="female",
                languages=["hi", "en", "hinglish"],
                vocal_archetype="sharp energetic alto",
                supported_emotions=["neutral", "impatient", "excited"],
            ),
            VoiceInfo(
                voice_id="mock_m_elder",
                name="The Caller",
                provider="mock",
                gender="male",
                languages=["hi", "hinglish"],
                vocal_archetype="weathered vintage voice",
                supported_emotions=["neutral", "haunting", "tearful"],
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
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        self.synthesis_calls.append({
            "text": text,
            "voice_id": voice_id,
            "line_id": line_id,
            "speed": speed,
            "pitch": pitch,
            "emotion": emotion,
        })

        if self.mode == "timeout":
            raise TTSProviderError("mock", line_id, "TTS request timed out after 30.0s", "Timeout")

        if self.mode == "quota_exceeded":
            raise TTSProviderError("mock", line_id, "Rate limit / quota exceeded (HTTP 429)", "QuotaExceeded")

        if self.mode == "invalid_voice" and voice_id == "non_existent_voice":
            raise TTSProviderError("mock", line_id, f"Voice ID '{voice_id}' is not supported.", "InvalidVoice")

        if self.mode == "corrupt_output":
            # Return under 100 bytes to trigger validation error
            return b"CORRUPT_AUDIO_BYTES_LESS_THAN_100"

        # Generate realistic PCM WAV audio bytes
        # Duration proportional to text length (approx 15 chars per second, clamped between 0.5s and 5.0s)
        base_duration = max(0.5, min(5.0, len(text) / 18.0))
        duration = base_duration / max(0.5, speed)
        num_samples = int(self.sample_rate * duration)

        # Base frequency modified slightly by pitch and voice
        base_freq = 220.0 if "f_" in voice_id else 130.0
        freq = base_freq * (2.0 ** (pitch / 12.0))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit PCM
            wav_file.setframerate(self.sample_rate)

            # Generate gentle sine wave with soft fade-in and fade-out to prevent clicks
            frames = bytearray()
            fade_samples = int(self.sample_rate * 0.05)  # 50ms fade
            for i in range(num_samples):
                # Calculate amplitude with envelope
                envelope = 1.0
                if i < fade_samples:
                    envelope = i / fade_samples
                elif i > num_samples - fade_samples:
                    envelope = (num_samples - i) / fade_samples

                val = int(envelope * 8000.0 * math.sin(2.0 * math.pi * freq * (i / self.sample_rate)))
                frames.extend(struct.pack("<h", val))

            wav_file.writeframes(frames)

        audio_bytes = buffer.getvalue()
        # Verify audio validity
        if len(audio_bytes) < 100:
            raise TTSProviderError("mock", line_id, "Generated audio was under minimum 100 bytes threshold.")

        return audio_bytes
