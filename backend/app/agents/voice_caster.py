from datetime import datetime, timezone
import json
import logging
from typing import Any
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.script import CastScript, GraphErrorRecord

logger = logging.getLogger(__name__)

# Standard Indian Multilingual Voice Catalog
DEFAULT_VOICE_CATALOG = [
    {"voice_id": "sarvam_m_kabir", "provider": "sarvam", "gender": "male", "vocal_archetype": "warm baritone, narrator, deep authority"},
    {"voice_id": "sarvam_f_ananya", "provider": "sarvam", "gender": "female", "vocal_archetype": "energetic young female, sharp producer alto"},
    {"voice_id": "sarvam_m_elder", "provider": "sarvam", "gender": "male", "vocal_archetype": "elderly grandfather, weathered trembling tenor"},
    {"voice_id": "sarvam_f_meera", "provider": "sarvam", "gender": "female", "vocal_archetype": "gentle emotional mother, soft melodic tone"},
    {"voice_id": "eleven_m_antagonist", "provider": "elevenlabs", "gender": "male", "vocal_archetype": "husky menacing conspirator"},
    {"voice_id": "eleven_f_detective", "provider": "elevenlabs", "gender": "female", "vocal_archetype": "assertive cool investigative investigator"},
]


async def voice_caster_node(state: KathaEpisodeState, llm: BaseLLMProvider) -> dict[str, Any]:
    """Voice Caster Agent: Assigns persistent character voice synthesis IDs from the voice catalog."""
    episode_id = state.get("episode_id", "unknown")
    logger.info(f"[{episode_id}] Executing Voice Caster Node")

    await event_hub.publish(
        episode_id=episode_id,
        event_type="node_started",
        node="voice_caster",
        payload={"message": "Casting acoustic vocal identities from multi-character voice catalog."},
    )

    # Check for forced mid-run failure simulation (for checkpoint testing)
    sim_flags = state.get("simulation_flags", {})
    if sim_flags.get("fail_at_node") == "voice_caster":
        err_msg = "Simulated forced failure at Voice Caster node for checkpoint recovery testing."
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_failed",
            node="voice_caster",
            payload={"error": err_msg},
        )
        raise RuntimeError(err_msg)

    localized_script = state.get("localized_script")
    outline = state.get("outline")

    if not localized_script or not outline:
        raise ValueError("Voice Caster requires both localized_script and outline in state.")

    # Collect unique character names
    unique_characters = set()
    for scene in localized_script.scenes:
        for line in scene.lines:
            unique_characters.add(line.character_name)

    catalog_json = json.dumps(DEFAULT_VOICE_CATALOG, indent=2)
    characters_json = json.dumps([c.model_dump() for c in outline.characters], indent=2)

    prompt = (
        f"Assign voice synthesis configurations for all characters in '{localized_script.title}'.\n"
        f"Target Language: {localized_script.target_language}\n"
        f"Characters Appearing in Script: {list(unique_characters)}\n\n"
        f"Character Archetypes from Outline:\n{characters_json}\n\n"
        f"Available Voice Catalog:\n{catalog_json}\n\n"
        f"Assign each character a unique, distinct voice matching their gender and acoustic texture.\n"
        f"Tag every localized line with its assigned voice_id."
    )
    system_prompt = (
        "You are the master Voice Caster Agent in Katha Studio. "
        "Ensure clear acoustic frequency contrast between conversation partners "
        "so listeners can easily distinguish who is speaking in an audio drama."
    )

    try:
        cast_script: CastScript = await llm.generate_structured(
            prompt=prompt,
            schema=CastScript,
            system_prompt=system_prompt,
        )
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="voice_caster",
            payload={
                "cast_count": len(cast_script.cast),
                "cast": [c.model_dump() for c in cast_script.cast],
            },
        )
        return {
            "cast_script": cast_script,
            "status": "CAST_COMPLETED",
            "current_node": "voice_caster",
        }
    except (LLMProviderError, SchemaValidationError) as exc:
        return {
            "status": "FAILED",
            "current_node": "voice_caster",
            "errors": [GraphErrorRecord(node="voice_caster", error=str(exc), timestamp=datetime.now(timezone.utc).isoformat(), recoverable=False)],
        }
