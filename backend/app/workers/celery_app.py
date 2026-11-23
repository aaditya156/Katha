"""Celery application for AditStudio background workers."""
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "katha_studio",
    broker=settings.CELERY_BROKER_URL,
    backend=None,  # PostgreSQL is source of truth; no Celery result backend needed
    include=[
        "app.workers.generation_tasks",
        "app.workers.audio_tasks",
    ],
)

celery_app.conf.update(
    # Serialization — JSON only, no pickle
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Reliability
    task_acks_late=True,            # Ack only after task completes (safe against worker crash)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,   # Fair dispatch; prevent task hoarding

    # Time limits
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,

    # Routing
    task_routes={
        "app.workers.generation_tasks.*": {"queue": "generation"},
        "app.workers.audio_tasks.*": {"queue": "audio"},
    },
    task_default_queue="generation",

    # Timezone
    timezone="UTC",
    enable_utc=True,
)
