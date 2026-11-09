from datetime import datetime, timezone
import json
import logging
from typing import Any
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.script import GraphErrorRecord, LocalizedScript

logger = logging.getLogger(__name__)


async def localizer_node(state: KathaEpisodeState, llm: BaseLLMProvider) -> dict[str, Any]:
    """Localizer Agent: Translates and adapts dialogue into authentic Hindi, Hinglish, or English."""
    episode_id = state.get("episode_id", "unknown")
    target_language = state.get("target_language", "hindi")
    logger.info(f"[{episode_id}] Executing Localizer Node for dialect: {target_language}")

    await event_hub.publish(
        episode_id=episode_id,
        event_type="node_started",
        node="localizer",
        payload={
            "target_language": target_language,
            "message": f"Localizing spoken dialogue into authentic {target_language}.",
        },
    )

    # Check for forced mid-run failure simulation (for checkpoint testing)
    sim_flags = state.get("simulation_flags", {})
    if sim_flags.get("fail_at_node") == "localizer":
        err_msg = "Simulated forced failure at Localizer node for checkpoint recovery testing."
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_failed",
            node="localizer",
            payload={"error": err_msg},
        )
        raise RuntimeError(err_msg)

    raw_script = state.get("raw_script")
    if not raw_script:
        raise ValueError("Localizer requires raw_script in state.")

    script_dump = json.dumps([
        {
            "scene_number": s.scene_number,
            "heading": s.heading,
            "atmosphere_soundscape": s.atmosphere_soundscape,
            "lines": [
                {
                    "id": l.id,
                    "line_number": l.line_number,
                    "character_name": l.character_name,
                    "text": l.text,
                    "stage_direction": l.stage_direction,
                    "emotion": l.emotion,
                    "pace": l.pace,
                }
                for l in s.lines
            ],
        }
        for s in raw_script.scenes
    ], indent=2)

    prompt = (
        f"Localize this entire audio drama script into {target_language.upper()}.\n"
        f"Title: {raw_script.title}\n"
        f"Target Language: {target_language}\n\n"
        f"Original Scenes & Dialogue:\n{script_dump}\n\n"
        f"Linguistic Rules for {target_language.upper()}:\n"
        f"- Hindi: Authentic, idiomatic Hindi with appropriate conversational honorifics (आप/तुम/तू) and dramatic texture.\n"
        f"- Hinglish: Urban colloquial code-switching blending Hindi and English words as spoken naturally in urban India.\n"
        f"- English: Expressive, dramatic Indian-English cadence and vernacular phrasing.\n"
        f"Preserve all line IDs, characters, stage directions, emotions, and pacing."
    )
    system_prompt = (
        "You are the master Localizer Agent in Katha Studio. "
        "Adapt dialogue so that it sounds completely spoken and alive to native ears, "
        "never like stiff machine translation."
    )

    try:
        localized: LocalizedScript = await llm.generate_structured(
            prompt=prompt,
            schema=LocalizedScript,
            system_prompt=system_prompt,
        )
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="localizer",
            payload={
                "target_language": localized.target_language,
                "scenes_count": len(localized.scenes),
                "total_lines": localized.total_lines,
            },
        )
        return {
            "localized_script": localized,
            "status": "LOCALIZED",
            "current_node": "localizer",
        }
    except (LLMProviderError, SchemaValidationError) as exc:
        return {
            "status": "FAILED",
            "current_node": "localizer",
            "errors": [GraphErrorRecord(node="localizer", error=str(exc), timestamp=datetime.now(timezone.utc).isoformat(), recoverable=False)],
        }

