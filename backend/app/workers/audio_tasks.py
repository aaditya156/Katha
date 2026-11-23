"""Audio processing Celery tasks — stub for Phase 4.2."""
import logging
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.audio_tasks.process_audio",
    queue="audio",
    bind=True,
    max_retries=2,
)
def process_audio(self: object, job_id: str) -> dict[str, str]:
    """Audio synthesis and assembly — implemented in Phase 4.2."""
    logger.info(f"Audio task stub invoked for job {job_id}. Phase 4.2 pending.")
    return {"status": "NOT_IMPLEMENTED", "job_id": job_id}
