from datetime import datetime, timezone
import logging
from typing import Any
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.script import BibleUpdatePayload, GraphErrorRecord

logger = logging.getLogger(__name__)


async def bible_updater_node(state: KathaEpisodeState, llm: BaseLLMProvider) -> dict[str, Any]:
    """Bible Updater Agent: Synthesizes episodic character arc evolutions and narrative lore."""
    episode_id = state.get("episode_id", "unknown")
    episode_num = state.get("episode_number", 1)
    logger.info(f"[{episode_id}] Executing Bible Updater Node for Episode {episode_num}")

    await event_hub.publish(
        episode_id=episode_id,
        event_type="node_started",
        node="bible_updater",
        payload={"message": "Updating episodic Story Bible continuity and character memory."},
    )

    # Check for forced mid-run failure simulation (for checkpoint testing)
    sim_flags = state.get("simulation_flags", {})
    if sim_flags.get("fail_at_node") == "bible_updater":
        err_msg = "Simulated forced failure at Bible Updater node for checkpoint recovery testing."
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_failed",
            node="bible_updater",
            payload={"error": err_msg},
        )
        raise RuntimeError(err_msg)

    cast_script = state.get("cast_script")
    outline = state.get("outline")

    if not cast_script or not outline:
        raise ValueError("Bible Updater requires cast_script and outline in state.")

    prompt = (
        f"Extract narrative continuity updates from Episode {episode_num}: '{cast_script.title}'.\n"
        f"Original Outline Premise: {outline.logline}\n"
        f"Cliffhanger / Resolution: {outline.cliffhanger_or_resolution}\n\n"
        f"Identify:\n"
        f"1. Concise 2-3 sentence episode summary.\n"
        f"2. How character relationships and psychological traits evolved.\n"
        f"3. Any new lore, secrets, or world rules established in this episode."
    )
    system_prompt = (
        "You are the master Story Bible Archivist in Katha Studio. "
        "Maintain episodic memory and world continuity across serialized audio drama releases."
    )

    try:
        bible_updates: BibleUpdatePayload = await llm.generate_structured(
            prompt=prompt,
            schema=BibleUpdatePayload,
            system_prompt=system_prompt,
        )
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="bible_updater",
            payload={"summary": bible_updates.episode_summary},
        )
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_completed",
            node="pipeline",
            payload={
                "message": "Episode pipeline generation completed successfully.",
                "total_lines": cast_script.total_lines,
                "critic_score": state.get("critic_score", 8.0),
                "revisions_used": state.get("revision_count", 0),
            },
        )
        return {
            "bible_updates": bible_updates,
            "status": "COMPLETED",
            "current_node": "bible_updater",
        }
    except (LLMProviderError, SchemaValidationError) as exc:
        return {
            "status": "FAILED",
            "current_node": "bible_updater",
            "errors": [GraphErrorRecord(node="bible_updater", error=str(exc), timestamp=datetime.now(timezone.utc).isoformat(), recoverable=False)],
        }
