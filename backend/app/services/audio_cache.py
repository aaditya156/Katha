import hashlib
import logging
import os
from pathlib import Path
from app.providers.tts.base import BaseTTSProvider, TTSProviderError

logger = logging.getLogger(__name__)

CACHE_DIR = Path("audio_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class AudioCacheService:
    """Deterministic hash-based audio snippet cache adhering to AGENTS.md."""

    def __init__(self, cache_dir: Path | str = CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_cache_key(
        self,
        text: str,
        voice_id: str,
        speed: float,
        pitch: float,
        emotion: str,
        provider_id: str,
        model_version: str,
    ) -> str:
        """Generate deterministic SHA-256 fingerprint for synthesis parameters."""
        normalized_text = text.strip().lower()
        normalized_emotion = emotion.strip().lower()
        content = (
            f"{normalized_text}:{voice_id}:{speed:.2f}:{pitch:.2f}:"
            f"{normalized_emotion}:{provider_id}:{model_version}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get_cached_path(self, cache_key: str, extension: str = "wav") -> Path | None:
        """Return path if valid cached audio exists (> 100 bytes), otherwise None."""
        path = self.cache_dir / f"{cache_key}.{extension}"
        if path.exists() and path.stat().st_size > 100:
            return path
        return None

    def save_audio(self, cache_key: str, audio_bytes: bytes, extension: str = "wav") -> Path:
        """Validate and persist audio bytes to disk."""
        if len(audio_bytes) < 100:
            raise ValueError(f"Audio payload for key '{cache_key}' is smaller than 100 bytes minimum.")

        path = self.cache_dir / f"{cache_key}.{extension}"
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return path

    async def get_or_synthesize(
        self,
        text: str,
        voice_id: str,
        line_id: str,
        tts: BaseTTSProvider,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: str = "neutral",
        extension: str = "wav",
    ) -> tuple[Path, bool]:
        """Fetch audio from cache or synthesize, returning (audio_path, was_cached)."""
        cache_key = self.compute_cache_key(
            text=text,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            emotion=emotion,
            provider_id=tts.provider_id,
            model_version=tts.model_version,
        )

        cached_path = self.get_cached_path(cache_key, extension=extension)
        if cached_path:
            logger.info(f"Audio cache HIT for line '{line_id}' ({cache_key[:8]})")
            return cached_path, True

        logger.info(f"Audio cache MISS for line '{line_id}'. Synthesizing with {tts.provider_id}...")
        audio_bytes = await tts.synthesize_line(
            text=text,
            voice_id=voice_id,
            line_id=line_id,
            speed=speed,
            pitch=pitch,
            emotion=emotion,
        )

        saved_path = self.save_audio(cache_key, audio_bytes, extension=extension)
        return saved_path, False


audio_cache = AudioCacheService()

