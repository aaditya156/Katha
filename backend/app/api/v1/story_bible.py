from typing import Annotated
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import AuthorizationFailedException, EntityNotFoundException
from app.models.series import Series
from app.models.story_bible import StoryBibleEntry
from app.models.user import User
from app.schemas.story_bible import (
    StoryBibleEntryCreate,
    StoryBibleEntryResponse,
    StoryBibleSearchRequest,
    StoryBibleSearchResponse,
)
from app.services.story_bible import story_bible_service

router = APIRouter(prefix="/series/{series_id}/bible", tags=["Story Bible"])


async def verify_series_ownership(
    series_id: str,
    user: User,
    db: AsyncSession,
) -> Series:
    """Helper to verify series exists and current user is owner."""
    series = await db.scalar(select(Series).where(Series.id == series_id))
    if not series:
        raise EntityNotFoundException("Series", series_id)
    if series.user_id != user.id and not user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to access this series' Story Bible.")
    return series


@router.get("", response_model=list[StoryBibleEntryResponse])
async def list_story_bible_entries(
    series_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    entity_type: str | None = Query(default=None, description="Filter by character, location, open_plot_thread, etc."),
) -> list[StoryBibleEntryResponse]:
    """List persistent Story Bible entries for a series."""
    await verify_series_ownership(series_id, current_user, db)

    stmt = select(StoryBibleEntry).where(StoryBibleEntry.series_id == series_id)
    if entity_type:
        stmt = stmt.where(StoryBibleEntry.entity_type == entity_type)
    stmt = stmt.order_by(StoryBibleEntry.created_at.desc())

    entries = (await db.scalars(stmt)).all()
    return [StoryBibleEntryResponse.model_validate(e) for e in entries]


@router.post("", response_model=StoryBibleEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_story_bible_entry(
    series_id: str,
    data: StoryBibleEntryCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StoryBibleEntryResponse:
    """Manually add a canonical lore entry to the series Story Bible."""
    await verify_series_ownership(series_id, current_user, db)

    # Compute embedding for dense retrieval
    embedding = await story_bible_service.embedding_provider.embed_text(
        f"[{data.entity_type.upper()}] {data.entity_name}: {data.content}"
    )

    entry = StoryBibleEntry(
        series_id=series_id,
        entity_type=data.entity_type,
        entity_name=data.entity_name,
        content=data.content,
        metadata_json=data.metadata_json,
        embedding=embedding,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return StoryBibleEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story_bible_entry(
    series_id: str,
    entry_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove a lore entry from the Story Bible."""
    await verify_series_ownership(series_id, current_user, db)

    entry = await db.scalar(
        select(StoryBibleEntry).where(
            StoryBibleEntry.id == entry_id,
            StoryBibleEntry.series_id == series_id,
        )
    )
    if not entry:
        raise EntityNotFoundException("StoryBibleEntry", entry_id)

    await db.delete(entry)
    await db.commit()


@router.post("/search", response_model=StoryBibleSearchResponse)
async def search_story_bible(
    series_id: str,
    payload: StoryBibleSearchRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StoryBibleSearchResponse:
    """Hybrid vector + keyword search over the Story Bible with RRF and continuity reranking."""
    await verify_series_ownership(series_id, current_user, db)

    return await story_bible_service.hybrid_search(
        series_id=series_id,
        query=payload.query,
        limit=payload.limit,
        retrieval_enabled=payload.retrieval_enabled,
        db=db,
    )
