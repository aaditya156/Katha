from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import AuthorizationFailedException, EntityNotFoundException
from app.models.series import Series
from app.models.user import User
from app.schemas.series import (
    SeriesCreate,
    SeriesDetailResponse,
    SeriesResponse,
    SeriesUpdate,
)

router = APIRouter(prefix="/series", tags=["Series"])


@router.post("", response_model=SeriesResponse, status_code=status.HTTP_201_CREATED)
async def create_series(
    data: SeriesCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeriesResponse:
    """Create a new narrative series belonging to the authenticated user."""
    series = Series(
        user_id=current_user.id,
        title=data.title,
        genre=data.genre,
        logline=data.logline,
        target_language=data.target_language,
        status="active",
    )
    db.add(series)
    await db.commit()
    await db.refresh(series)
    return SeriesResponse.model_validate(series)


@router.get("", response_model=list[SeriesResponse])
async def list_user_series(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SeriesResponse]:
    """List all series owned by the authenticated user."""
    query = (
        select(Series)
        .where(Series.user_id == current_user.id)
        .order_by(Series.created_at.desc())
    )
    result = await db.scalars(query)
    return [SeriesResponse.model_validate(s) for s in result.all()]


@router.get("/{series_id}", response_model=SeriesDetailResponse)
async def get_series_detail(
    series_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeriesDetailResponse:
    """Get single series with its child episodes, strictly enforcing ownership."""
    query = (
        select(Series)
        .options(selectinload(Series.episodes))
        .where(Series.id == series_id)
    )
    series = await db.scalar(query)

    if not series:
        raise EntityNotFoundException("Series", series_id)

    if series.user_id != current_user.id and not current_user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to view this series.")

    return SeriesDetailResponse.model_validate(series)


@router.put("/{series_id}", response_model=SeriesResponse)
async def update_series(
    series_id: str,
    data: SeriesUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeriesResponse:
    """Update metadata for an existing series, strictly enforcing ownership."""
    series = await db.scalar(select(Series).where(Series.id == series_id))

    if not series:
        raise EntityNotFoundException("Series", series_id)

    if series.user_id != current_user.id and not current_user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to modify this series.")

    update_dict = data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(series, field, value)

    await db.commit()
    await db.refresh(series)
    return SeriesResponse.model_validate(series)


@router.delete("/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(
    series_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a series and all its nested episodes, strictly enforcing ownership."""
    series = await db.scalar(select(Series).where(Series.id == series_id))

    if not series:
        raise EntityNotFoundException("Series", series_id)

    if series.user_id != current_user.id and not current_user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to delete this series.")

    await db.delete(series)
    await db.commit()
