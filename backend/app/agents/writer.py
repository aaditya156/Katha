from datetime import datetime, timezone
import json
import logging
from typing import Any
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.script import GraphErrorRecord, Script, ScriptScene

logger = logging.getLogger(__name__)


async def writer_node(state: KathaEpisodeState, llm: BaseLLMProvider) -> dict[str, Any]:
    """Writer Agent: Generates full multi-character script or rewrites ONLY failing scenes."""
    episode_id = state.get("episode_id", "unknown")
    revision_count = state.get("revision_count", 0)
    failing_scenes = state.get("failing_scenes", [])
    existing_script = state.get("raw_script")
    current_critique = state.get("current_critique")
    outline = state.get("outline")

    if not outline:
        raise ValueError("Cannot execute Writer node without an EpisodeOutline in state.")

    # Check for forced mid-run failure simulation (for checkpoint testing)
    sim_flags = state.get("simulation_flags", {})
    if sim_flags.get("fail_at_node") == "writer":
        err_msg = "Simulated forced failure at Writer node for checkpoint recovery testing."
        await event_hub.publish(
            episode_id=episode_id,
            event_type="pipeline_failed",
            node="writer",
            payload={"error": err_msg},
        )
        raise RuntimeError(err_msg)

    # Retrieve relevant Story Bible memories for character voice & continuity
    series_id = state.get("series_id", "")
    story_bible_context = ""
    retrieval_override = sim_flags.get("retrieval_enabled")

    try:
        from app.services.story_bible import story_bible_service

        search_res = await story_bible_service.hybrid_search(
            series_id=series_id,
            query=f"{outline.title} {outline.logline}",
            limit=4,
            retrieval_enabled=retrieval_override,
        )
        if search_res.status == "RETRIEVAL_SUCCESS":
            memories = "\n".join(f"- [{r.entry.entity_type.upper()}] {r.entry.entity_name}: {r.entry.content}" for r in search_res.results)
            story_bible_context = f"\nRelevant Story Bible Memories & Character Lore:\n{memories}\n"
            logger.info(f"[{episode_id}] Injected {len(search_res.results)} Story Bible memories into Writer.")
        elif search_res.status == "RETRIEVAL_DISABLED":
            logger.info(f"[{episode_id}] Story Bible retrieval disabled for Writer (Ablation).")
    except Exception as exc:
        logger.error(f"[{episode_id}] Story Bible retrieval error in Writer: {exc}")
        if sim_flags.get("fail_on_retrieval_error"):
            raise

    # REVISION MODE: Rewrite ONLY failing scenes
    if existing_script and failing_scenes:
        logger.info(f"[{episode_id}] Writer in REVISION mode (Cycle {revision_count + 1}): Rewriting failing scenes {failing_scenes}")
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_started",
            node="writer",
            payload={
                "mode": "revision",
                "revision_count": revision_count,
                "failing_scenes": failing_scenes,
                "message": f"Targeting only failing scenes {failing_scenes} for rewrite.",
            },
        )

        critique_map = {}
        if current_critique:
            for sc in current_critique.scene_critiques:
                critique_map[sc.scene_number] = sc

        updated_scenes: list[ScriptScene] = []
        for orig_scene in existing_script.scenes:
            if orig_scene.scene_number in failing_scenes:
                sc_critique = critique_map.get(orig_scene.scene_number)
                critique_feedback = (
                    f"Issues: {', '.join(sc_critique.issues)}\n"
                    f"Suggested Improvements: {sc_critique.suggested_improvements}"
                    if sc_critique
                    else "Improve dialogue naturalness, pacing, and emotional tension."
                )

                prompt = (
                    f"Rewrite ONLY Scene {orig_scene.scene_number} of the audio drama '{outline.title}'.\n"
                    f"Scene Heading: {orig_scene.heading}\n"
                    f"Atmosphere / Soundscape: {orig_scene.atmosphere_soundscape}\n"
                    f"Characters Present: {', '.join(orig_scene.characters_present)}\n"
                    f"{story_bible_context}"
                    f"Original Spoken Lines:\n"
                    + "\n".join(f"[{l.character_name}]: {l.text} ({l.stage_direction})" for l in orig_scene.lines)
                    + f"\n\nCRITIQUE FEEDBACK TO ADDRESS IN REWRITE:\n{critique_feedback}\n"
                )
                system_prompt = (
                    "You are the master Writer Agent in Katha Studio. "
                    "Rewrite ONLY this specific failing scene to resolve all critique issues. "
                    "Ensure high audio drama immersion, crisp subtext, and clear emotional arcs."
                )

                try:
                    rewritten_scene: ScriptScene = await llm.generate_structured(
                        prompt=prompt,
                        schema=ScriptScene,
                        system_prompt=system_prompt,
                    )
                    # Enforce proper scene number
                    rewritten_scene = rewritten_scene.model_copy(update={"scene_number": orig_scene.scene_number})
                    updated_scenes.append(rewritten_scene)
                    await event_hub.publish(
                        episode_id=episode_id,
                        event_type="scene_rewritten",
                        node="writer",
                        payload={"scene_number": orig_scene.scene_number, "lines_count": len(rewritten_scene.lines)},
                    )
                except (LLMProviderError, SchemaValidationError) as exc:
                    return {
                        "status": "FAILED",
                        "current_node": "writer",
                        "errors": [GraphErrorRecord(node="writer", error=str(exc), timestamp=datetime.now(timezone.utc).isoformat(), recoverable=False)],
                    }
            else:
                # Passing scene: PRESERVE EXACTLY UNTOUCHED
                updated_scenes.append(orig_scene)

        total_lines = sum(len(sc.lines) for sc in updated_scenes)
        revised_script = existing_script.model_copy(update={"scenes": updated_scenes, "total_lines": total_lines})

        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="writer",
            payload={
                "mode": "revision",
                "revision_count": revision_count,
                "rewritten_scenes": failing_scenes,
                "total_lines": total_lines,
            },
        )
        return {
            "raw_script": revised_script,
            "revision_count": revision_count + 1,
            "failing_scenes": [],  # Cleared until next critique evaluation
            "status": "REVISED",
            "current_node": "writer",
        }

    # INITIAL DRAFT GENERATION
    logger.info(f"[{episode_id}] Writer in INITIAL DRAFT mode: Generating scene dialogue")
    await event_hub.publish(
        episode_id=episode_id,
        event_type="node_started",
        node="writer",
        payload={"mode": "initial", "message": "Drafting multi-character dialogue across all outline scenes."},
    )

    scenes_json = json.dumps([s.model_dump() for s in outline.scenes], indent=2)
    prompt = (
        f"Write the complete dialogue script for the audio drama '{outline.title}'.\n"
        f"Target Language: {state.get('target_language', 'hindi')}\n"
        f"Target Duration: {state.get('target_duration_minutes', 5)} minutes\n"
        f"Logline: {outline.logline}\n\n"
        f"{story_bible_context}"
        f"Outline Scenes Specification:\n{scenes_json}\n\n"
        f"Write complete, rich, multi-character dialogue lines for every scene."
    )
    system_prompt = (
        "You are the master Writer Agent in Katha Studio. "
        "Create rich, natural dialogue with stage directions indicating audio sound cues, "
        "whispers, emotional shifts, and pacing. Keep scenes tight, atmospheric, and compelling."
    )

    try:
        script: Script = await llm.generate_structured(
            prompt=prompt,
            schema=Script,
            system_prompt=system_prompt,
        )
        await event_hub.publish(
            episode_id=episode_id,
            event_type="node_completed",
            node="writer",
            payload={
                "mode": "initial",
                "title": script.title,
                "scenes_count": len(script.scenes),
                "total_lines": script.total_lines,
            },
        )
        return {
            "raw_script": script,
            "status": "WRITING_COMPLETED",
            "current_node": "writer",
        }
    except (LLMProviderError, SchemaValidationError) as exc:
        return {
            "status": "FAILED",
            "current_node": "writer",
            "errors": [GraphErrorRecord(node="writer", error=str(exc), timestamp=datetime.now(timezone.utc).isoformat(), recoverable=False)],
        }
