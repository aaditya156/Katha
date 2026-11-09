from pathlib import Path
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_active_user, get_db
from app.core.config import get_settings
from app.core.exceptions import AuthorizationFailedException, EntityNotFoundException
from app.models.episode import Episode
from app.models.series import Series
from app.models.user import User
from app.providers.tts.base import BaseTTSProvider
from app.providers.tts.elevenlabs import ElevenLabsTTSProvider
from app.providers.tts.mock import MockTTSProvider
from app.providers.tts.sarvam import SarvamTTSProvider
from app.services.audio_orchestrator import audio_orchestrator

router = APIRouter(prefix="/episodes", tags=["Audio"])
settings = get_settings()


def get_tts_provider() -> BaseTTSProvider:
    """Dependency that returns the configured TTS provider instance."""
    provider_name = settings.TTS_DEFAULT_PROVIDER.lower()
    if provider_name == "sarvam":
        return SarvamTTSProvider()
    elif provider_name == "elevenlabs":
        return ElevenLabsTTSProvider()
    else:
        return MockTTSProvider()


class UpdateLineRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    text: str | None = Field(default=None, min_length=1)
    emotion: str | None = None
    voice_id: str | None = None


@router.post("/{episode_id}/audio/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_episode_audio(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    tts: Annotated[BaseTTSProvider, Depends(get_tts_provider)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Synthesize all episode dialogue lines in parallel and assemble master audio track."""
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != current_user.id and not current_user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to generate audio for this episode.")

    master_path = await audio_orchestrator.synthesize_episode_audio(episode_id, tts)

    return {
        "status": "COMPLETED",
        "episode_id": episode_id,
        "audio_url": f"/api/v1/episodes/{episode_id}/audio",
        "file_path": str(master_path),
    }


@router.get("/{episode_id}/audio")
async def get_episode_audio_file(
    episode_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    """Stream or serve the master assembled audio track for an episode."""
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    master_path = Path("audio_cache") / "episodes" / episode_id / "master.wav"
    if not master_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Master audio file has not been generated for this episode yet.",
        )

    return FileResponse(
        path=master_path,
        media_type="audio/wav",
        filename=f"katha_episode_{episode.episode_number}.wav",
    )


@router.post("/{episode_id}/lines/{line_id}/regenerate")
async def regenerate_line_audio(
    episode_id: str,
    line_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    tts: Annotated[BaseTTSProvider, Depends(get_tts_provider)],
    db: Annotated[AsyncSession, Depends(get_db)],
    req: UpdateLineRequest | None = None,
) -> dict[str, Any]:
    """Regenerate a single dialogue line and re-stitch the master audio track without touching unchanged lines."""
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != current_user.id and not current_user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to modify this episode.")

    new_text = req.text if req else None
    new_emotion = req.emotion if req else None
    new_voice_id = req.voice_id if req else None

    master_file, timeline = await audio_orchestrator.regenerate_single_line(
        episode_id=episode_id,
        line_id=line_id,
        tts=tts,
        new_text=new_text,
        new_emotion=new_emotion,
        new_voice_id=new_voice_id,
    )

    return {
        "status": "COMPLETED",
        "line_id": line_id,
        "audio_url": f"/api/v1/episodes/{episode_id}/audio",
        "timeline_items": len(timeline),
    }
