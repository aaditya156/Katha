"""
Celery generation worker: executes LangGraph pipeline in a durable background process.

Design:
- Worker creates its own asyncio event loop, DB engine and checkpointer.
- Never shares FastAPI's event-loop-bound DB connections or checkpointer.
- Task args are only serializable IDs — never live objects or sessions.
- Job state is persisted to PostgreSQL before and after execution.
- Redis Pub/Sub events are published from the worker process.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.workers.celery_app import celery_app
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GenerationTask(Task):
    """Base task providing per-worker async event loop lifecycle."""
    abstract = True
    _loop: asyncio.AbstractEventLoop | None = None

    def get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def run_async(self, coro: Any) -> Any:
        return self.get_loop().run_until_complete(coro)


@celery_app.task(
    bind=True,
    base=GenerationTask,
    name="app.workers.generation_tasks.run_generation",
    queue="generation",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def run_generation(self: "GenerationTask", job_id: str) -> dict[str, Any]:
    """Execute LangGraph story generation for a BackgroundJob. Only arg: job_id (str)."""
    return self.run_async(_async_run_generation(self, job_id))


async def _publish_worker_event(episode_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Publish SSE event from worker via Redis Pub/Sub (cross-process safe)."""
    import json
    from redis.asyncio import Redis as AsyncRedis
    event_data = {
        "episode_id": episode_id,
        "event_type": event_type,
        "node": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    try:
        redis = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.publish(f"episode:{episode_id}", json.dumps(event_data))
        await redis.aclose()
    except Exception as exc:
        logger.warning(f"Worker could not publish event {event_type} to Redis: {exc}")


async def _mark_job_failed(
    job_id: str, error_code: str, error_message: str
) -> None:
    """Persist FAILED status in a fresh DB session — safe from error/timeout handlers."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy import select
        from app.models.job import BackgroundJob

        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sf() as db:
            job = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if job and not job.is_terminal():
                job.status = "FAILED"
                job.error_code = error_code
                job.error_message = error_message[:500]
                job.finished_at = datetime.now(timezone.utc)
                job.updated_at = datetime.now(timezone.utc)
                await db.commit()
        await engine.dispose()
    except Exception as e:
        logger.error(f"Failed to persist job failure for {job_id}: {e}")


async def _async_run_generation(task: "GenerationTask", job_id: str) -> dict[str, Any]:
    """Async implementation of generation pipeline — runs in worker's own event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.models.job import BackgroundJob
    from app.models.episode import Episode
    from app.models.series import Series
    from app.agents.checkpointer import get_in_memory_checkpointer
    from app.agents.graph import create_katha_graph
    from app.agents.state import KathaEpisodeState
    from app.providers.factory import get_llm_provider

    # Worker creates its own DB engine — never reuses FastAPI's asyncpg pool
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    episode_id = "unknown"
    try:
        # 1. Load job
        async with session_factory() as db:
            job = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if not job:
                logger.error(f"BackgroundJob {job_id} not found.")
                await engine.dispose()
                return {"status": "NOT_FOUND", "job_id": job_id}

            if job.is_terminal():
                logger.info(f"Job {job_id} already terminal ({job.status}) — skipping.")
                await engine.dispose()
                return {"status": job.status, "job_id": job_id, "episode_id": job.episode_id}

            episode_id = job.episode_id
            meta = job.metadata_json or {}

            # 2. Mark RUNNING
            job.status = "RUNNING"
            job.celery_task_id = task.request.id or str(uuid.uuid4())
            job.started_at = datetime.now(timezone.utc)
            job.current_stage = "initializing"
            job.dispatch_pending = 0
            job.updated_at = datetime.now(timezone.utc)
            await db.commit()

        await _publish_worker_event(episode_id, "pipeline_started", {"job_id": job_id})

        # 3. Load episode + series
        async with session_factory() as db:
            episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if not episode:
                raise ValueError(f"Episode {episode_id} not found.")
            series = await db.scalar(select(Series).where(Series.id == episode.series_id))
            if not series:
                raise ValueError(f"Series {episode.series_id} not found.")

            episode.status = "WRITING"
            await db.commit()

            # Capture plain values before session closes
            ep_number = episode.episode_number
            ep_premise = episode.premise
            ep_target_lang = episode.target_language
            ep_duration = episode.duration_minutes_target
            ep_outline = episode.outline
            series_id = series.id
            series_genre = series.genre

        # 4. Update progress
        async with session_factory() as db:
            job2 = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if job2:
                job2.current_stage = "generating"
                job2.progress = 20
                job2.updated_at = datetime.now(timezone.utc)
                await db.commit()

        # 5. Build LLM provider from config
        provider_id = meta.get("provider", settings.LLM_DEFAULT_PROVIDER)
        model_name = meta.get("model_name")
        exec_mode = "MOCK" if provider_id == "mock" else "LIVE"
        llm = get_llm_provider(provider_id, model_name, exec_mode)

        # 6. Build initial state
        initial_state: KathaEpisodeState = {
            "series_id": series_id,
            "episode_id": episode_id,
            "episode_number": ep_number,
            "premise": ep_premise,
            "target_language": ep_target_lang,
            "target_duration_minutes": ep_duration,
            "genre": series_genre,
            "characters_hint": [],
            "revision_count": 0,
            "critique_history": [],
            "errors": [],
            "failing_scenes": [],
            "status": "INITIALIZED",
            "current_node": "start",
            "simulation_flags": meta.get("simulation_flags", {}),
        }
        if ep_outline:
            try:
                from app.schemas.outline import EpisodeOutline
                initial_state["outline"] = EpisodeOutline.model_validate(ep_outline)
            except Exception:
                pass

        # 7. Use in-memory checkpointer in workers
        # (PostgreSQL checkpointer uses asyncpg which requires app startup; MemorySaver is safe)
        checkpointer = get_in_memory_checkpointer()
        graph = create_katha_graph(llm=llm, checkpointer=checkpointer)
        config = {"configurable": {"thread_id": episode_id}}

        await _publish_worker_event(episode_id, "node_started", {"node": "planner", "job_id": job_id})

        # 8. Execute LangGraph pipeline
        final_state = await graph.ainvoke(initial_state, config=config)

        # 9. Persist results
        async with session_factory() as db:
            ep2 = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if ep2:
                if final_state.get("outline"):
                    ep2.outline = final_state["outline"].model_dump()
                if final_state.get("cast_script"):
                    ep2.script = final_state["cast_script"].model_dump()
                ep2.status = "READY" if final_state.get("status") == "COMPLETED" else "FAILED"
                await db.commit()

            job3 = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if job3:
                final_status = "SUCCEEDED" if final_state.get("status") == "COMPLETED" else "FAILED"
                job3.status = final_status
                job3.progress = 100
                job3.current_stage = "completed"
                job3.finished_at = datetime.now(timezone.utc)
                job3.updated_at = datetime.now(timezone.utc)
                await db.commit()

        await _publish_worker_event(
            episode_id, "pipeline_completed",
            {"job_id": job_id, "status": final_state.get("status")}
        )
        await engine.dispose()
        return {"status": "SUCCEEDED", "job_id": job_id, "episode_id": episode_id}

    except SoftTimeLimitExceeded:
        logger.error(f"Job {job_id} soft time limit exceeded.")
        await _mark_job_failed(job_id, "TIMEOUT", "Task exceeded time limit.")
        await engine.dispose()
        raise

    except Exception as exc:
        logger.error(f"Generation job {job_id} failed: {exc}", exc_info=True)
        await _mark_job_failed(job_id, "PIPELINE_ERROR", str(exc))
        await _publish_worker_event(episode_id, "pipeline_failed", {"error": str(exc)[:200], "job_id": job_id})
        await engine.dispose()

        retry_num = task.request.retries
        if retry_num < (task.max_retries or 3):
            raise task.retry(exc=exc, countdown=30 * (2 ** retry_num))
        raise
