from typing import Annotated
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.runner import launch_background_generation, pipeline_service
from app.api.deps import get_current_active_user, get_llm_provider, security_scheme
from app.core.database import get_db
from app.core.events import event_hub
from app.core.exceptions import (
    AuthenticationFailedException,
    AuthorizationFailedException,
    EntityNotFoundException,
)
from app.core.security import decode_token
from app.models.episode import Episode
from app.models.series import Series
from app.models.user import User
from app.providers.base import BaseLLMProvider

router = APIRouter(prefix="/generation", tags=["Generation"])


@router.post("/episodes/{episode_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_episode_generation(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm: Annotated[BaseLLMProvider, Depends(get_llm_provider)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Trigger the cyclical LangGraph story generation pipeline as an idempotent background job."""
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != current_user.id and not current_user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to generate this episode.")

    is_new = launch_background_generation(episode_id, llm)

    return {
        "status": "RUNNING",
        "episode_id": episode_id,
        "message": "Generation job dispatched." if is_new else "Generation job already in progress.",
    }


@router.get("/episodes/{episode_id}/events")
async def stream_episode_events(
    episode_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)] = None,
    token: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """Server-Sent Events (SSE) endpoint streaming real-time pipeline execution progress."""
    auth_token = credentials.credentials if credentials else token
    if not auth_token:
        raise AuthenticationFailedException(detail="Authorization credentials were not provided.")

    payload = decode_token(auth_token)
    user_id = payload.get("sub")
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user or not user.is_active:
        raise AuthenticationFailedException(detail="User account is invalid or deactivated.")

    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != user.id and not user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to observe this stream.")

    return StreamingResponse(
        event_hub.subscribe(episode_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
