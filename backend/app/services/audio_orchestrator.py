import asyncio
import logging
from pathlib import Path
from typing import Any
from sqlalchemy import select
from app.core.database import async_session_factory
from app.core.events import event_hub
from app.models.episode import Episode
from app.providers.tts.base import BaseTTSProvider
from app.services.audio_assembler import audio_assembler
from app.services.audio_cache import audio_cache

logger = logging.getLogger(__name__)


class AudioOrchestrationService:
    """Coordinates parallel TTS synthesis, caching, and episode timeline assembly."""

    def __init__(self, concurrency_limit: int = 5) -> None:
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    async def synthesize_episode_audio(
        self,
        episode_id: str,
        tts: BaseTTSProvider,
    ) -> Path:
        """Synthesize all lines in parallel with bounded concurrency and assemble master track."""
        async with async_session_factory() as db:
            episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if not episode:
                raise ValueError(f"Episode '{episode_id}' not found.")
            if not episode.script:
                raise ValueError(f"Episode '{episode_id}' does not have a generated script.")

            script_data = dict(episode.script)

        scenes = script_data.get("scenes", [])
        if not scenes:
            raise ValueError(f"No scenes found in script for episode '{episode_id}'.")

        # Collect all dialogue lines
        flattened_lines: list[dict[str, Any]] = []
        for scene_idx, scene in enumerate(scenes):
            lines = scene.get("lines", [])
            for line_idx, line in enumerate(lines):
                is_scene_break = (line_idx == len(lines) - 1) and (scene_idx < len(scenes) - 1)
                flattened_lines.append({
                    "line_id": line["id"],
                    "character_name": line["character_name"],
                    "text": line.get("text_localized") or line.get("text", ""),
                    "voice_id": line.get("voice_id") or "sarvam_m_kabir",
                    "speed": float(line.get("speed", 1.0)),
                    "pitch": float(line.get("pitch", 0.0)),
                    "emotion": line.get("emotion", "neutral"),
                    "is_scene_break": is_scene_break,
                })

        total_lines = len(flattened_lines)
        completed_count = 0

        await event_hub.publish(
            episode_id=episode_id,
            event_type="tts_batch_started",
            payload={"total_lines": total_lines},
        )

        async def _synthesize_single_line(line_item: dict[str, Any]) -> dict[str, Any]:
            nonlocal completed_count
            async with self.semaphore:
                path, was_cached = await audio_cache.get_or_synthesize(
                    text=line_item["text"],
                    voice_id=line_item["voice_id"],
                    line_id=line_item["line_id"],
                    tts=tts,
                    speed=line_item["speed"],
                    pitch=line_item["pitch"],
                    emotion=line_item["emotion"],
                )
                completed_count += 1
                await event_hub.publish(
                    episode_id=episode_id,
                    event_type="tts_line_completed",
                    payload={
                        "line_id": line_item["line_id"],
                        "was_cached": was_cached,
                        "progress": f"{completed_count}/{total_lines}",
                    },
                )
                return {
                    "line_id": line_item["line_id"],
                    "character_name": line_item["character_name"],
                    "audio_path": path,
                    "is_scene_break": line_item["is_scene_break"],
                }

        # Run synthesis tasks concurrently with bounded concurrency
        assembly_entries = await asyncio.gather(*[_synthesize_single_line(item) for item in flattened_lines])

        # Assemble master track
        await event_hub.publish(
            episode_id=episode_id,
            event_type="audio_assembly_started",
            payload={"message": "Stitching master audio timeline and calculating offsets."},
        )

        master_path = Path("audio_cache") / "episodes" / episode_id / "master.wav"
        output_file, timeline = await audio_assembler.assemble_episode(assembly_entries, master_path)

        # Update Episode in DB
        async with async_session_factory() as db:
            ep = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if ep:
                script_update = dict(ep.script) if ep.script else {}
                script_update["timeline"] = timeline
                ep.script = script_update
                ep.audio_url = f"/api/v1/episodes/{episode_id}/audio"
                await db.commit()

        await event_hub.publish(
            episode_id=episode_id,
            event_type="audio_generation_completed",
            payload={
                "audio_url": f"/api/v1/episodes/{episode_id}/audio",
                "timeline_items": len(timeline),
            },
        )
        return output_file

    async def regenerate_single_line(
        self,
        episode_id: str,
        line_id: str,
        tts: BaseTTSProvider,
        new_text: str | None = None,
        new_emotion: str | None = None,
        new_voice_id: str | None = None,
    ) -> tuple[Path, list[dict[str, Any]]]:
        """Regenerate a single dialogue line and re-stitch the master audio track without touching unchanged lines."""
        async with async_session_factory() as db:
            episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if not episode or not episode.script:
                raise ValueError(f"Episode '{episode_id}' or script not found.")

            script_data = dict(episode.script)

        # Find target line in script
        target_found = False
        target_item = None
        flattened_lines: list[dict[str, Any]] = []

        for scene_idx, scene in enumerate(script_data.get("scenes", [])):
            lines = scene.get("lines", [])
            for line_idx, line in enumerate(lines):
                is_scene_break = (line_idx == len(lines) - 1) and (scene_idx < len(script_data["scenes"]) - 1)

                if line["id"] == line_id:
                    target_found = True
                    if new_text is not None:
                        line["text_localized"] = new_text
                        line["text"] = new_text
                    if new_emotion is not None:
                        line["emotion"] = new_emotion
                    if new_voice_id is not None:
                        line["voice_id"] = new_voice_id
                    target_item = line

                flattened_lines.append({
                    "line_id": line["id"],
                    "character_name": line["character_name"],
                    "text": line.get("text_localized") or line.get("text", ""),
                    "voice_id": line.get("voice_id") or "sarvam_m_kabir",
                    "speed": float(line.get("speed", 1.0)),
                    "pitch": float(line.get("pitch", 0.0)),
                    "emotion": line.get("emotion", "neutral"),
                    "is_scene_break": is_scene_break,
                })

        if not target_found or not target_item:
            raise ValueError(f"Line '{line_id}' was not found in episode '{episode_id}'.")

        # 1. Synthesize ONLY the modified line (forces cache re-computation)
        new_line_path, _ = await audio_cache.get_or_synthesize(
            text=target_item.get("text_localized") or target_item.get("text", ""),
            voice_id=target_item.get("voice_id") or "sarvam_m_kabir",
            line_id=line_id,
            tts=tts,
            speed=float(target_item.get("speed", 1.0)),
            pitch=float(target_item.get("pitch", 0.0)),
            emotion=target_item.get("emotion", "neutral"),
        )

        # 2. Gather audio paths for all lines (untouched lines hit cache instantly)
        assembly_entries = []
        for item in flattened_lines:
            if item["line_id"] == line_id:
                assembly_entries.append({
                    "line_id": line_id,
                    "character_name": item["character_name"],
                    "audio_path": new_line_path,
                    "is_scene_break": item["is_scene_break"],
                })
            else:
                path, _ = await audio_cache.get_or_synthesize(
                    text=item["text"],
                    voice_id=item["voice_id"],
                    line_id=item["line_id"],
                    tts=tts,
                    speed=item["speed"],
                    pitch=item["pitch"],
                    emotion=item["emotion"],
                )
                assembly_entries.append({
                    "line_id": item["line_id"],
                    "character_name": item["character_name"],
                    "audio_path": path,
                    "is_scene_break": item["is_scene_break"],
                })

        # 3. Re-stitch master audio track
        master_path = Path("audio_cache") / "episodes" / episode_id / "master.wav"
        output_file, timeline = await audio_assembler.assemble_episode(assembly_entries, master_path)

        # 4. Save updated script & timeline to DB
        async with async_session_factory() as db:
            ep = await db.scalar(select(Episode).where(Episode.id == episode_id))
            if ep:
                script_data["timeline"] = timeline
                ep.script = script_data
                ep.audio_url = f"/api/v1/episodes/{episode_id}/audio"
                await db.commit()

        await event_hub.publish(
            episode_id=episode_id,
            event_type="line_regenerated",
            payload={"line_id": line_id, "audio_url": f"/api/v1/episodes/{episode_id}/audio"},
        )
        return output_file, timeline


audio_orchestrator = AudioOrchestrationService()

