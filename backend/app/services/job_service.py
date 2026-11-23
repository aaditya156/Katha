"""
BackgroundJob service: transactional outbox dispatch, concurrency safety and state management.

Guarantees:
  1. Concurrency-safe job creation: handles concurrent API requests via unique constraint and IntegrityError catch.
  2. Transactional outbox pattern: dispatch_pending=1 until Celery accepts task.
  3. Safe redispatch: only redispatches QUEUED jobs whose dispatch was never confirmed (celery_task_id is None).
  4. Sanitized error reporting: API never exposes secrets or stack traces.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import BackgroundJob
from app.core.exceptions import AuthorizationFailedException
from app.core.sanitizer import sanitize_error_message

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"QUEUED", "RUNNING", "RETRYING"})


async def get_or_create_generation_job(
    db: AsyncSession,
    episode_id: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[BackgroundJob, bool]:
    """
    Get existing active generation job or create a new one in a concurrency-safe manner.
    Returns (job, is_new).
    """
    existing = await db.scalar(
        select(BackgroundJob).where(
            and_(
                BackgroundJob.episode_id == episode_id,
                BackgroundJob.job_type == "generation",
                BackgroundJob.status.in_(ACTIVE_STATUSES),
            )
        )
    )

    if existing:
        if existing.user_id != user_id:
            raise AuthorizationFailedException("Active generation job belongs to another user.")
        logger.info(f"Reusing active job {existing.id} for episode {episode_id}")
        return existing, False

    now = datetime.now(timezone.utc)
    job = BackgroundJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        episode_id=episode_id,
        job_type="generation",
        status="QUEUED",
        progress=0,
        current_stage="queued",
        retry_count=0,
        max_retries=3,
        queued_at=now,
        dispatch_pending=1,
        metadata_json=metadata or {},
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    try:
        await db.commit()
        await db.refresh(job)
        logger.info(f"Created BackgroundJob {job.id} for episode {episode_id}")
        return job, True
    except IntegrityError:
        # Concurrent request created an active job first
        await db.rollback()
        concurrent_job = await db.scalar(
            select(BackgroundJob).where(
                and_(
                    BackgroundJob.episode_id == episode_id,
                    BackgroundJob.job_type == "generation",
                    BackgroundJob.status.in_(ACTIVE_STATUSES),
                )
            )
        )
        if concurrent_job:
            if concurrent_job.user_id != user_id:
                raise AuthorizationFailedException("Active generation job belongs to another user.")
            logger.info(f"Resolved race: reusing concurrent active job {concurrent_job.id}")
            return concurrent_job, False
        raise


def dispatch_generation_task(job_id: str) -> str:
    """Dispatch job to Celery generation queue. Returns the Celery task ID."""
    from app.workers.generation_tasks import run_generation
    result = run_generation.apply_async(args=[job_id], queue="generation")
    logger.info(f"Dispatched Celery task {result.id} for job {job_id}")
    return result.id


async def update_celery_task_id(db: AsyncSession, job_id: str, celery_task_id: str) -> None:
    """Record Celery task ID and clear dispatch_pending flag to confirm dispatch."""
    job = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
    if job:
        job.celery_task_id = celery_task_id
        job.dispatch_pending = 0
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()


async def redispatch_pending_jobs() -> int:
    """
    Recovery: redispatch genuinely un-dispatched QUEUED jobs (celery_task_id is None).
    Called on startup to recover from crash between DB commit and Celery broker dispatch.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.core.config import get_settings
    settings = get_settings()

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    count = 0
    try:
        async with sf() as db:
            # Only pick up jobs that are QUEUED, marked pending, and NEVER received a celery_task_id
            pending = (await db.scalars(
                select(BackgroundJob).where(
                    and_(
                        BackgroundJob.status == "QUEUED",
                        BackgroundJob.dispatch_pending == 1,
                        BackgroundJob.celery_task_id.is_(None),
                    )
                )
            )).all()

            for job in pending:
                try:
                    task_id = dispatch_generation_task(job.id)
                    job.celery_task_id = task_id
                    job.dispatch_pending = 0
                    job.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    count += 1
                    logger.info(f"Redispatched genuinely pending job {job.id} -> Celery task {task_id}")
                except Exception as exc:
                    logger.error(f"Failed to redispatch job {job.id}: {exc}")
    except Exception as exc:
        logger.warning(f"Pending job redispatch skipped (broker or DB unavailable): {exc}")
    finally:
        await engine.dispose()
    return count


def build_job_response(job: BackgroundJob) -> dict[str, Any]:
    """Safe API response dict — sanitized error message, no secrets, no stack traces."""
    safe_error = sanitize_error_message(job.error_message) if job.error_message else None
    return {
        "id": job.id,
        "episode_id": job.episode_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "current_stage": job.current_stage,
        "celery_task_id": job.celery_task_id,
        "retry_count": job.retry_count,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_message": safe_error,
        "error_code": job.error_code,
    }
