"""Background job status API — enforces ownership."""
from typing import Annotated, Any
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import AuthorizationFailedException, EntityNotFoundException
from app.models.job import BackgroundJob
from app.models.user import User
from app.services.job_service import build_job_response

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=dict[str, Any])
async def get_job_status(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Get job status. Users can only view their own jobs."""
    job = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
    if not job:
        raise EntityNotFoundException("BackgroundJob", job_id)
    if job.user_id != current_user.id and not current_user.is_superuser:
        raise AuthorizationFailedException("You do not have permission to view this job.")
    return build_job_response(job)
