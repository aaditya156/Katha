from datetime import datetime, timezone
import json
import logging
from typing import Any
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.script import CritiqueReport, GraphErrorRecord

logger = logging.getLogger(__name__)


async def critic_node(state: KathaEpisodeState, llm: BaseLLMProvider) -> dict[str, Any]:
    """Critic Agent: Evaluates consistency, coherence, naturalness, pacing, and safety."""
    episode_id = state.get("episode_id", "unknown")
    logger.info(f"[{episode_id}] Executing Critic Node")

    await event_hub.publish(
        episode_id=episode_id,
        event_type="node_started",
        node="critic",
        payload={"message": "Analyzing dramatic pacing, dialogue naturalness, and safety."},
    )

    # Check for forced mid-run failure simulation (for checkpoint testing)
    sim_flags = state.get("simulation_flags", {})
    if sim_flags.get("fail_at_node") == "critic":
        err_msg = "Simulated forced failure at Critic node for checkpoint recovery testing."
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_failed",
            node="critic",
            payload={"error": err_msg},
        )
        raise RuntimeError(err_msg)

    raw_script = state.get("raw_script")
    outline = state.get("outline")

    if not raw_script or not outline:
        raise ValueError("Critic requires both outline and raw_script in state.")

    script_summary = json.dumps([
        {
            "scene_number": s.scene_number,
            "heading": s.heading,
            "lines": [f"[{l.character_name}]: {l.text}" for l in s.lines],
        }
        for s in raw_script.scenes
    ], indent=2)

    prompt = (
        f"Critique this audio drama script for '{raw_script.title}'.\n"
        f"Target Language: {state.get('target_language', 'hindi')}\n"
        f"Target Duration: {state.get('target_duration_minutes', 5)} minutes\n"
        f"Original Outline Premise: {outline.premise if hasattr(outline, 'premise') else outline.logline}\n\n"
        f"Full Script by Scenes:\n{script_summary}\n\n"
        f"Evaluate strictly on:\n"
        f"1. Consistency with characters and world.\n"
        f"2. Coherence of dramatic beats.\n"
        f"3. Naturalness of dialogue cadence for audio.\n"
        f"4. Pacing and scene economy.\n"
        f"5. Audio safety and emotional appropriateness.\n\n"
        f"For EACH scene, evaluate if it passed (score >= 7.0) and identify any failing scene numbers."
    )
    system_prompt = (
        "You are the master Critic Agent in Katha Studio. "
        "Provide rigorous, objective dramatic analysis. "
        "A script passes if overall score is >= 7.5 and NO scenes fail. "
        "If any scene has dialogue exposition, weak conflict, or poor pacing, mark it as failing with actionable suggestions."
    )

    try:
        critique: CritiqueReport = await llm.generate_structured(
            prompt=prompt,
            schema=CritiqueReport,
            system_prompt=system_prompt,
        )

        failing = critique.failing_scene_numbers or [
            sc.scene_number for sc in critique.scene_critiques if not sc.passed
        ]

        # Invariant check: Never treat failed evaluations as passing
        is_passed = critique.passed and len(failing) == 0 and critique.score >= 7.5

        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="critic",
            payload={
                "score": critique.score,
                "passed": is_passed,
                "failing_scenes": failing,
                "feedback": critique.feedback,
            },
        )

        return {
            "current_critique": critique,
            "critique_history": [critique],
            "critic_score": critique.score,
            "failing_scenes": failing,
            "status": "CRITIQUE_COMPLETED",
            "current_node": "critic",
        }
    except (LLMProviderError, SchemaValidationError) as exc:
        return {
            "status": "FAILED",
            "current_node": "critic",
            "errors": [GraphErrorRecord(node="critic", error=str(exc), timestamp=datetime.now(timezone.utc).isoformat(), recoverable=False)],
        }
