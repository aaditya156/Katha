"""Generation API — HTTP 202 with job_id; Celery worker handles execution."""
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, security_scheme
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
from app.services.job_service import (
    build_job_response,
    dispatch_generation_task,
    get_or_create_generation_job,
    update_celery_task_id,
)

router = APIRouter(prefix="/generation", tags=["Generation"])


@router.post(
    "/episodes/{episode_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
async def trigger_episode_generation(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: str = Query(default="mock"),
    model_name: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Trigger episode generation. Returns HTTP 202 with job_id.

    - If an active job already exists for this episode, returns it (idempotent).
    - New job: persisted first (dispatch_pending=1), then dispatched to Celery.
    - On broker unavailability, job remains QUEUED and will be redispatched on startup.
    """
    # Validate episode ownership
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != current_user.id and not current_user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to generate this episode.")

    metadata = {"provider": provider, "model_name": model_name}

    # Get or create persistent job (outbox: dispatch_pending=1)
    job, is_new = await get_or_create_generation_job(
        db=db,
        episode_id=episode_id,
        user_id=current_user.id,
        metadata=metadata,
    )

    if is_new:
        # Dispatch to Celery AFTER successful DB commit
        try:
            celery_task_id = dispatch_generation_task(job.id)
            await update_celery_task_id(db, job.id, celery_task_id)
        except Exception as exc:
            # Broker unavailable: job stays QUEUED+dispatch_pending=1 for recovery
            import logging
            logging.getLogger(__name__).warning(
                f"Celery dispatch failed for job {job.id}: {exc}. "
                "Job is persisted and will be redispatched on startup."
            )

    response = build_job_response(job)
    response["message"] = "Generation job created." if is_new else "Generation job already in progress."
    return response


@router.get("/episodes/{episode_id}/events")
async def stream_episode_events(
    episode_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)] = None,
    token: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """Server-Sent Events streaming real-time pipeline progress."""
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
