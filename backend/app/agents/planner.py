from datetime import datetime, timezone
import logging
from typing import Any
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.outline import EpisodeOutline
from app.schemas.script import GraphErrorRecord

logger = logging.getLogger(__name__)


async def planner_node(state: KathaEpisodeState, llm: BaseLLMProvider) -> dict[str, Any]:
    """Planner Agent: Constructs the beat-by-beat dramatic episode outline."""
    episode_id = state.get("episode_id", "unknown")
    logger.info(f"[{episode_id}] Executing Planner Node")

    await event_hub.publish(
        episode_id=episode_id,
        event_type="node_started",
        node="planner",
        payload={"message": "Planning episode dramatic structure and acoustic soundscapes."},
    )

    # Check for forced mid-run failure simulation (for checkpoint testing)
    sim_flags = state.get("simulation_flags", {})
    if sim_flags.get("fail_at_node") == "planner":
        err_msg = "Simulated forced failure at Planner node for checkpoint recovery testing."
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_failed",
            node="planner",
            payload={"error": err_msg},
        )
        raise RuntimeError(err_msg)

    # If outline is already present in state, reuse and validate it
    existing_outline = state.get("outline")
    if existing_outline:
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="planner",
            payload={"title": existing_outline.title, "reused": True},
        )
        return {
            "status": "PLANNING_COMPLETED",
            "current_node": "planner",
        }

    premise = state.get("premise", "")
    target_language = state.get("target_language", "hindi")
    duration = state.get("target_duration_minutes", 5)
    genre = state.get("genre", "drama")
    characters_hint = state.get("characters_hint") or []

    prompt = (
        f"Generate a compelling, production-ready audio story episode outline.\n"
        f"Genre: {genre}\n"
        f"Target Language: {target_language}\n"
        f"Target Duration: {duration} minutes\n"
        f"Premise / Seed Concept: {premise}\n"
    )
    if characters_hint:
        prompt += f"Suggested Characters: {', '.join(characters_hint)}\n"

    system_prompt = (
        "You are the master Planner Agent in Katha Studio. "
        "Create rich, emotionally gripping scene breakdowns with acoustic soundscape instructions "
        "and clear dramatic conflict beats designed specifically for the audio medium."
    )

    try:
        outline: EpisodeOutline = await llm.generate_structured(
            prompt=prompt,
            schema=EpisodeOutline,
            system_prompt=system_prompt,
        )
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="planner",
            payload={
                "title": outline.title,
                "scene_count": len(outline.scenes),
                "character_count": len(outline.characters),
            },
        )
        return {
            "outline": outline,
            "status": "PLANNING_COMPLETED",
            "current_node": "planner",
        }
    except (LLMProviderError, SchemaValidationError) as exc:
        err_record = GraphErrorRecord(
            node="planner",
            error=str(exc),
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=False,
        )
        return {
            "status": "FAILED",
            "current_node": "planner",
            "errors": [err_record],
        }
