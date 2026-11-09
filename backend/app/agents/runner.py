import asyncio
from datetime import datetime, timezone
import logging
from typing import Any
from sqlalchemy import select
from app.agents.checkpointer import get_in_memory_checkpointer
from app.agents.graph import create_katha_graph
from app.agents.state import KathaEpisodeState
from app.core.database import async_session_factory
from app.core.events import event_hub
from app.models.episode import Episode
from app.models.series import Series
from app.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

# Active in-flight background tasks for idempotency tracking
_running_jobs: dict[str, asyncio.Task[Any]] = {}


class EpisodePipelineService:
    """Orchestrates LangGraph pipeline execution, checkpointing, and DB synchronization."""

    def __init__(self, checkpointer: Any = None) -> None:
        self.checkpointer = checkpointer or get_in_memory_checkpointer()

    async def run_pipeline(
        self,
        episode_id: str,
        llm: BaseLLMProvider,
        initial_state_overrides: dict[str, Any] | None = None,
    ) -> KathaEpisodeState:
        """Run or resume the LangGraph episodic pipeline for a given episode."""
        # 1. Fetch episode and series metadata from DB
        async with async_session_factory() as db:
            episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if not episode:
                raise ValueError(f"Episode '{episode_id}' not found.")
            series = await db.scalar(select(Series).where(Series.id == episode.series_id))
            if not series:
                raise ValueError(f"Parent Series '{episode.series_id}' not found.")

            # Update DB status to RUNNING
            episode.status = "WRITING"
            await db.commit()

        # 2. Build initial state or resume checkpoint
        initial_state: KathaEpisodeState = {
            "series_id": series.id,
            "episode_id": episode.id,
            "episode_number": episode.episode_number,
            "premise": episode.premise,
            "target_language": episode.target_language,
            "target_duration_minutes": episode.duration_minutes_target,
            "genre": series.genre,
            "characters_hint": [],
            "revision_count": 0,
            "critique_history": [],
            "errors": [],
            "failing_scenes": [],
            "status": "INITIALIZED",
            "current_node": "start",
            "simulation_flags": {},
        }

        if initial_state_overrides:
            initial_state.update(initial_state_overrides)

        # Reuse outline if stored in DB
        if episode.outline and not initial_state.get("outline"):
            try:
                from app.schemas.outline import EpisodeOutline
                initial_state["outline"] = EpisodeOutline.model_validate(episode.outline)
            except Exception:
                pass

        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_started",
            payload={"episode_number": episode.episode_number, "title": episode.title},
        )

        # 3. Construct Graph with Checkpointer
        graph = create_katha_graph(llm=llm, checkpointer=self.checkpointer)
        config = {"configurable": {"thread_id": episode_id}}

        try:
            # Execute LangGraph asynchronously
            final_state = await graph.ainvoke(initial_state, config=config)

            # 4. Synchronize results to Database
            async with async_session_factory() as db:
                ep = await db.scalar(select(Episode).where(Episode.id == episode_id))
                if ep:
                    if final_state.get("outline"):
                        ep.outline = final_state["outline"].model_dump()
                    if final_state.get("cast_script"):
                        ep.script = final_state["cast_script"].model_dump()
                    ep.status = "READY" if final_state.get("status") == "COMPLETED" else "FAILED"
                    await db.commit()

            return final_state

        except Exception as exc:
            logger.error(f"Pipeline error for episode {episode_id}: {exc}", exc_info=True)
            async with async_session_factory() as db:
                ep = await db.scalar(select(Episode).where(Episode.id == episode_id))
                if ep:
                    ep.status = "FAILED"
                    await db.commit()

            await event_hub.publish(
                episode_id=episode_id,
                event_type="pipeline_failed",
                payload={"error": str(exc)},
            )
            raise


pipeline_service = EpisodePipelineService()


def launch_background_generation(
    episode_id: str,
    llm: BaseLLMProvider,
) -> bool:
    """Launch episode generation in an idempotent background task."""
    if episode_id in _running_jobs and not _running_jobs[episode_id].done():
        logger.info(f"Generation job for episode {episode_id} is already in flight. Reusing task.")
        return False

    async def _runner() -> None:
        try:
            await pipeline_service.run_pipeline(episode_id, llm)
        finally:
            _running_jobs.pop(episode_id, None)

    task = asyncio.create_task(_runner())
    _running_jobs[episode_id] = task
    return True

