from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_active_user, get_llm_provider
from app.core.database import get_db
from app.core.exceptions import AuthorizationFailedException, EntityNotFoundException
from app.models.episode import Episode
from app.models.series import Series
from app.models.user import User
from app.providers.base import BaseLLMProvider
from app.schemas.episode import (
    EpisodeCreate,
    EpisodeResponse,
    EpisodeUpdate,
)
from app.schemas.outline import EpisodeOutline, GenerateOutlineRequest

router = APIRouter(prefix="/episodes", tags=["Episodes"])


@router.post("", response_model=EpisodeResponse, status_code=status.HTTP_201_CREATED)
async def create_episode(
    data: EpisodeCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EpisodeResponse:
    """Create a new episode inside a user's series."""
    series = await db.scalar(select(Series).where(Series.id == data.series_id))
    if not series:
        raise EntityNotFoundException("Series", data.series_id)

    if series.user_id != current_user.id and not current_user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to add episodes to this series.")

    episode = Episode(
        series_id=data.series_id,
        episode_number=data.episode_number,
        title=data.title,
        premise=data.premise,
        target_language=data.target_language,
        duration_minutes_target=data.duration_minutes_target,
        status="DRAFT",
    )
    db.add(episode)
    await db.commit()
    await db.refresh(episode)
    return EpisodeResponse.model_validate(episode)


@router.get("/series/{series_id}", response_model=list[EpisodeResponse])
async def list_series_episodes(
    series_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EpisodeResponse]:
    """List all episodes in a series, verifying series ownership."""
    series = await db.scalar(select(Series).where(Series.id == series_id))
    if not series:
        raise EntityNotFoundException("Series", series_id)

    if series.user_id != current_user.id and not current_user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to view episodes for this series.")

    query = (
        select(Episode)
        .where(Episode.series_id == series_id)
        .order_by(Episode.episode_number.asc())
    )
    result = await db.scalars(query)
    return [EpisodeResponse.model_validate(ep) for ep in result.all()]


@router.get("/{episode_id}", response_model=EpisodeResponse)
async def get_episode_detail(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EpisodeResponse:
    """Get episode details, verifying series ownership."""
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != current_user.id and not current_user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to view this episode.")

    return EpisodeResponse.model_validate(episode)


@router.put("/{episode_id}", response_model=EpisodeResponse)
async def update_episode(
    episode_id: str,
    data: EpisodeUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EpisodeResponse:
    """Update episode metadata or status."""
    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or (series.user_id != current_user.id and not current_user.is_superuser):
        raise AuthorizationFailedException("You do not have permission to modify this episode.")

    update_dict = data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(episode, field, value)

    await db.commit()
    await db.refresh(episode)
    return EpisodeResponse.model_validate(episode)


@router.post("/generate-outline", response_model=EpisodeOutline)
async def generate_episode_outline(
    req: GenerateOutlineRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm: Annotated[BaseLLMProvider, Depends(get_llm_provider)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EpisodeOutline:
    """Generate a structured, beat-by-beat dramatic episode outline via LLM Provider."""
    series_context = ""
    if req.series_id:
        series = await db.scalar(select(Series).where(Series.id == req.series_id))
        if not series:
            raise EntityNotFoundException("Series", req.series_id)
        if series.user_id != current_user.id and not current_user.is_superuser:
            raise AuthorizationFailedException("You do not have permission to access this series.")
        series_context = f"\nSeries Title: {series.title}\nSeries Logline: {series.logline}\nSeries Genre: {series.genre}"

    prompt = (
        f"Generate a compelling, production-ready audio story episode outline.{series_context}\n"
        f"Episode Number: {req.episode_number}\n"
        f"Target Language: {req.target_language}\n"
        f"Target Duration: {req.target_duration_minutes} minutes\n"
        f"Premise / Seed Concept: {req.premise}\n"
    )
    if req.characters_hint:
        prompt += f"Suggested Characters: {', '.join(req.characters_hint)}\n"

    system_prompt = (
        "You are the master Planner Agent in Katha Studio, a premium audio drama production engine. "
        "Create rich, emotionally gripping scene breakdowns with acoustic soundscape instructions "
        "and clear dramatic conflict beats designed specifically for the audio medium."
    )

    outline: EpisodeOutline = await llm.generate_structured(
        prompt=prompt,
        schema=EpisodeOutline,
        system_prompt=system_prompt,
    )

    return outline

