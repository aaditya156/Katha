"""
Celery generation worker: executes LangGraph pipeline in a durable, retryable background process.

Key Guarantees:
- Worker-owned event loop and DB connection pool.
- Worker-owned AsyncPostgresSaver checkpointer with deterministic lifecycle.
- Initializes EventHub so all LangGraph agents stream cross-process over Redis Pub/Sub.
- Atomic conditional job claiming: prevents duplicate execution on duplicate Celery delivery.
- Proper retry lifecycle: RETRYING on intermediate failures, FAILED only when retries exhausted.
- Measured progress tracking driven by actual LangGraph node transitions.
- Sanitized error reporting: API keys, secrets, and internal stack traces are redacted.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import uuid
from typing import Any, AsyncGenerator

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.workers.celery_app import celery_app
from app.core.config import get_settings
from app.core.events import event_hub
from app.core.sanitizer import sanitize_error_message
from app.models.job import BackgroundJob
from app.models.episode import Episode
from app.models.series import Series
from app.agents.checkpointer import get_in_memory_checkpointer
from app.agents.graph import create_katha_graph
from app.agents.state import KathaEpisodeState
from app.providers.factory import get_llm_provider

logger = logging.getLogger(__name__)
settings = get_settings()

# Stage and progress mappings for real LangGraph node completions
NODE_PROGRESS_MAP = {
    "planner": ("writing", 30),
    "writer": ("critiquing", 55),
    "critic": ("localizing", 70),
    "localizer": ("voice_casting", 85),
    "voice_caster": ("updating_story_bible", 92),
    "bible_updater": ("completed", 100),
}


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


@asynccontextmanager
async def get_worker_checkpointer() -> AsyncGenerator[Any, None]:
    """Provide a worker-owned checkpointer instance with strict resource cleanup."""
    if settings.DATABASE_URL.startswith("sqlite"):
        yield get_in_memory_checkpointer()
        return

    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    pool = None
    try:
        pool = AsyncConnectionPool(
            conninfo=pg_url,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        await pool.open()
        saver = AsyncPostgresSaver(conn=pool)
        await saver.setup()
        yield saver
    except Exception as exc:
        if settings.ENVIRONMENT == "production":
            logger.critical(f"Worker failed to initialize durable PostgreSQL checkpointer: {exc}", exc_info=True)
            raise RuntimeError(f"Failed to initialize durable PostgreSQL checkpointer: {exc}") from exc
        logger.warning(f"Worker checkpointer falling back to memory in non-production: {exc}")
        yield get_in_memory_checkpointer()
    finally:
        if pool is not None:
            try:
                await pool.close()
            except Exception as exc:
                logger.warning(f"Error closing worker checkpointer pool: {exc}")


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
    """Execute LangGraph story generation for a BackgroundJob."""
    return self.run_async(_async_run_generation(self, job_id))


async def _async_run_generation(task: "GenerationTask", job_id: str) -> dict[str, Any]:
    """Async worker execution with atomic claiming, real checkpointing, and Redis SSE."""
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    episode_id = "unknown"
    max_retries = 3

    # Initialize EventHub inside worker process so all LangGraph nodes stream via Redis
    await event_hub.initialize()

    try:
        # 1. ATOMIC CLAIM: Only claim if status is QUEUED or RETRYING
        # Prevents duplicate task execution on redeliveries or concurrent worker claims
        now = datetime.now(timezone.utc)
        claim_stmt = (
            update(BackgroundJob)
            .where(
                and_(
                    BackgroundJob.id == job_id,
                    BackgroundJob.status.in_(["QUEUED", "RETRYING"]),
                )
            )
            .values(
                status="RUNNING",
                celery_task_id=task.request.id or str(uuid.uuid4()),
                started_at=now,
                current_stage="initializing",
                progress=5,
                dispatch_pending=0,
                updated_at=now,
            )
            .returning(
                BackgroundJob.id,
                BackgroundJob.episode_id,
                BackgroundJob.user_id,
                BackgroundJob.metadata_json,
                BackgroundJob.retry_count,
                BackgroundJob.max_retries,
            )
        )

        async with session_factory() as db:
            result = await db.execute(claim_stmt)
            claimed = result.first()
            await db.commit()

        if not claimed:
            # Check existing state to log accurately
            async with session_factory() as db:
                existing = await db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if existing:
                logger.info(
                    f"Job {job_id} not claimable (status={existing.status}). "
                    "Skipping duplicate or terminal task execution."
                )
                return {"status": existing.status, "job_id": job_id, "skipped": True}
            logger.error(f"BackgroundJob {job_id} not found.")
            return {"status": "NOT_FOUND", "job_id": job_id}

        _, episode_id, user_id, meta_json, retry_count, max_retries = claimed
        meta = meta_json or {}

        await event_hub.publish(
            episode_id,
            "pipeline_started",
            {"job_id": job_id, "attempt": task.request.retries + 1},
        )

        # 2. Fetch Episode & Series metadata
        async with session_factory() as db:
            episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if not episode:
                raise ValueError(f"Episode {episode_id} not found.")
            series = await db.scalar(select(Series).where(Series.id == episode.series_id))
            if not series:
                raise ValueError(f"Series {episode.series_id} not found.")

            episode.status = "WRITING"
            await db.commit()

            ep_number = episode.episode_number
            ep_premise = episode.premise
            ep_target_lang = episode.target_language
            ep_duration = episode.duration_minutes_target
            ep_outline = episode.outline
            series_id = series.id
            series_genre = series.genre

        # 3. Build LLM provider from config
        provider_id = meta.get("provider", settings.LLM_DEFAULT_PROVIDER)
        model_name = meta.get("model_name")
        exec_mode = "MOCK" if provider_id == "mock" else "LIVE"
        llm = get_llm_provider(provider_id, model_name, exec_mode)

        # 4. Prepare initial state
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

        config = {"configurable": {"thread_id": episode_id}}

        # 5. Execute LangGraph with worker-owned checkpointer & real progress updates
        async with get_worker_checkpointer() as checkpointer:
            graph = create_katha_graph(llm=llm, checkpointer=checkpointer)

            # Check if this thread has an existing checkpoint (resumption path)
            existing_checkpoint = await checkpointer.aget_tuple(config)
            start_input = None if (existing_checkpoint and existing_checkpoint.checkpoint) else initial_state

            # Stream updates node by node to measure true progress
            async for update_chunk in graph.astream(start_input, config=config, stream_mode="updates"):
                for node_name in update_chunk.keys():
                    if node_name in NODE_PROGRESS_MAP:
                        stage, prog = NODE_PROGRESS_MAP[node_name]
                        async with session_factory() as db:
                            await db.execute(
                                update(BackgroundJob)
                                .where(BackgroundJob.id == job_id)
                                .values(
                                    current_stage=stage,
                                    progress=prog,
                                    updated_at=datetime.now(timezone.utc),
                                )
                            )
                            await db.commit()

            # Retrieve final state from durable checkpoint
            final_snapshot = await graph.aget_state(config)
            final_state = final_snapshot.values

        # 6. Check workflow outcome and persist
        is_completed = final_state.get("status") == "COMPLETED"

        async with session_factory() as db:
            ep = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if ep:
                if final_state.get("outline"):
                    ep.outline = final_state["outline"].model_dump()
                if final_state.get("cast_script"):
                    ep.script = final_state["cast_script"].model_dump()
                ep.status = "READY" if is_completed else "FAILED"
                await db.commit()

            final_job_status = "SUCCEEDED" if is_completed else "FAILED"
            now_finish = datetime.now(timezone.utc)
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status=final_job_status,
                    progress=100 if is_completed else 95,
                    current_stage="completed" if is_completed else "failed",
                    finished_at=now_finish,
                    updated_at=now_finish,
                )
            )
            await db.commit()

        if is_completed:
            await event_hub.publish(
                episode_id,
                "pipeline_completed",
                {"job_id": job_id, "status": "COMPLETED"},
            )
            return {"status": "SUCCEEDED", "job_id": job_id, "episode_id": episode_id}
        else:
            raise RuntimeError(f"Pipeline finished with uncompleted status: {final_state.get('status')}")

    except SoftTimeLimitExceeded as exc:
        safe_msg = sanitize_error_message("Task execution soft time limit exceeded.")
        logger.error(f"Job {job_id} soft time limit exceeded: {safe_msg}")
        await _handle_job_failure(
            session_factory=session_factory,
            task=task,
            job_id=job_id,
            episode_id=episode_id,
            error_code="TIMEOUT",
            error_message=safe_msg,
            exc=exc,
            max_retries=max_retries,
        )
        raise

    except Exception as exc:
        safe_msg = sanitize_error_message(exc)
        logger.error(f"Generation job {job_id} encountered error: {safe_msg}", exc_info=True)
        await _handle_job_failure(
            session_factory=session_factory,
            task=task,
            job_id=job_id,
            episode_id=episode_id,
            error_code="PIPELINE_ERROR",
            error_message=safe_msg,
            exc=exc,
            max_retries=max_retries,
        )

    finally:
        await event_hub.close()
        await engine.dispose()


async def _handle_job_failure(
    session_factory: async_sessionmaker[AsyncSession],
    task: "GenerationTask",
    job_id: str,
    episode_id: str,
    error_code: str,
    error_message: str,
    exc: Exception,
    max_retries: int,
) -> None:
    """Correct Celery retry lifecycle: RETRYING on intermediate, FAILED on exhausted."""
    current_retry = task.request.retries
    now = datetime.now(timezone.utc)

    if current_retry < max_retries:
        # RETRYABLE: Update job to RETRYING and persist attempt count + sanitized error
        next_attempt = current_retry + 1
        async with session_factory() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status="RETRYING",
                    retry_count=next_attempt,
                    error_code=error_code,
                    error_message=error_message,
                    updated_at=now,
                )
            )
            await db.commit()

        await event_hub.publish(
            episode_id,
            "pipeline_retrying",
            {"job_id": job_id, "retry_count": next_attempt, "error": error_message},
        )

        countdown = min(30 * (2 ** current_retry), 300)
        logger.info(f"Retrying job {job_id} (attempt {next_attempt}/{max_retries}) in {countdown}s.")
        raise task.retry(exc=exc, countdown=countdown)

    else:
        # EXHAUSTED: Final terminal FAILED status
        async with session_factory() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status="FAILED",
                    retry_count=current_retry,
                    error_code="RETRIES_EXHAUSTED",
                    error_message=f"Exhausted {max_retries} retries: {error_message}",
                    finished_at=now,
                    updated_at=now,
                )
            )
            ep = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if ep:
                ep.status = "FAILED"
            await db.commit()

        await event_hub.publish(
            episode_id,
            "pipeline_failed",
            {"job_id": job_id, "error": error_message},
        )
        raise exc
