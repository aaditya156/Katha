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
    series_id = state.get("series_id", "")

    # Retrieve relevant Story Bible memories
    story_bible_context = ""
    sim_flags = state.get("simulation_flags", {})
    retrieval_override = sim_flags.get("retrieval_enabled")

    try:
        from app.services.story_bible import story_bible_service
        search_res = await story_bible_service.hybrid_search(
            series_id=series_id,
            query=premise,
            limit=4,
            retrieval_enabled=retrieval_override,
        )
        if search_res.status == "RETRIEVAL_SUCCESS":
            memories = "\n".join(f"- [{r.entry.entity_type.upper()}] {r.entry.entity_name}: {r.entry.content}" for r in search_res.results)
            story_bible_context = f"\nRelevant Story Bible Memories & Lore:\n{memories}\n"
            logger.info(f"[{episode_id}] Injected {len(search_res.results)} Story Bible memories into Planner.")
        elif search_res.status == "RETRIEVAL_DISABLED":
            logger.info(f"[{episode_id}] Story Bible retrieval disabled for this generation (Ablation).")
    except Exception as exc:
        logger.error(f"[{episode_id}] Story Bible retrieval error in Planner: {exc}")
        # Never swallow retrieval failure silently
        if sim_flags.get("fail_on_retrieval_error"):
            raise

    prompt = (
        f"Generate a compelling, production-ready audio story episode outline.\n"
        f"Genre: {genre}\n"
        f"Target Language: {target_language}\n"
        f"Target Duration: {duration} minutes\n"
        f"Premise / Seed Concept: {premise}\n"
        f"{story_bible_context}"
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
