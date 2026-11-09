import asyncio
import io
import logging
import os
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Any
import wave

logger = logging.getLogger(__name__)


class TimelineEntry:
    def __init__(
        self,
        line_id: str,
        character_name: str,
        start_seconds: float,
        end_seconds: float,
        duration_seconds: float,
    ) -> None:
        self.line_id = line_id
        self.character_name = character_name
        self.start_seconds = round(start_seconds, 3)
        self.end_seconds = round(end_seconds, 3)
        self.duration_seconds = round(duration_seconds, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "character_name": self.character_name,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "duration_seconds": self.duration_seconds,
        }


class FFmpegAudioAssembler:
    """Assembles audio snippets into broadcast-standard master episode tracks with timeline manifests."""

    def __init__(
        self,
        inter_line_pause_ms: int = 250,
        scene_pause_ms: int = 800,
        sample_rate: int = 24000,
    ) -> None:
        self.inter_line_pause_ms = inter_line_pause_ms
        self.scene_pause_ms = scene_pause_ms
        self.sample_rate = sample_rate
        self.ffmpeg_path = shutil.which("ffmpeg")

    def _generate_silence_frames(self, duration_ms: int, sample_rate: int = 24000) -> bytes:
        """Generate silent PCM frames for pacing pauses."""
        num_samples = int(sample_rate * (duration_ms / 1000.0))
        return b"\x00\x00" * num_samples

    def assemble_sync(
        self,
        line_entries: list[dict[str, Any]],
        output_path: Path,
    ) -> tuple[Path, list[dict[str, Any]]]:
        """Synchronously concatenate line audio files with inter-speaker pauses and generate timeline manifest.

        Args:
            line_entries: list of dicts: {'line_id': str, 'character_name': str, 'audio_path': Path, 'is_scene_break': bool}
            output_path: Destination path for master audio file
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        timeline: list[dict[str, Any]] = []

        total_frames = bytearray()
        current_time_seconds = 0.0

        for idx, entry in enumerate(line_entries):
            audio_path = Path(entry["audio_path"])
            if not audio_path.exists() or audio_path.stat().st_size < 100:
                raise ValueError(f"Audio file '{audio_path}' for line '{entry.get('line_id')}' is missing or invalid.")

            # Read line WAV frames
            with wave.open(str(audio_path), "rb") as w:
                n_channels = w.getnchannels()
                sampwidth = w.getsampwidth()
                framerate = w.getframerate()
                n_frames = w.getnframes()
                frames = w.readframes(n_frames)

            line_duration = n_frames / float(framerate)
            start_time = current_time_seconds
            end_time = start_time + line_duration

            timeline.append(
                TimelineEntry(
                    line_id=entry["line_id"],
                    character_name=entry["character_name"],
                    start_seconds=start_time,
                    end_seconds=end_time,
                    duration_seconds=line_duration,
                ).to_dict()
            )

            total_frames.extend(frames)
            current_time_seconds = end_time

            # Insert pause between dialogue lines (unless it's the very last line)
            if idx < len(line_entries) - 1:
                pause_ms = self.scene_pause_ms if entry.get("is_scene_break") else self.inter_line_pause_ms
                silence = self._generate_silence_frames(pause_ms, sample_rate=framerate)
                total_frames.extend(silence)
                current_time_seconds += pause_ms / 1000.0

        # Write intermediate combined WAV
        temp_combined_wav = output_path.with_suffix(".tmp.wav")
        with wave.open(str(temp_combined_wav), "wb") as out_wav:
            out_wav.setnchannels(1)
            out_wav.setsampwidth(2)
            out_wav.setframerate(self.sample_rate)
            out_wav.writeframes(total_frames)

        # Apply FFmpeg loudness normalization if binary is available
        if self.ffmpeg_path:
            logger.info("Applying FFmpeg EBU R128 loudness normalization (loudnorm=I=-16:TP=-1.5:LRA=11)...")
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", str(temp_combined_wav),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                str(output_path),
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                temp_combined_wav.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning(f"FFmpeg normalization failed ({exc}); falling back to unnormalized master.")
                shutil.move(str(temp_combined_wav), str(output_path))
        else:
            # Move unnormalized WAV into place
            shutil.move(str(temp_combined_wav), str(output_path))

        return output_path, timeline

    async def assemble_episode(
        self,
        line_entries: list[dict[str, Any]],
        output_path: Path,
    ) -> tuple[Path, list[dict[str, Any]]]:
        """Asynchronous non-blocking wrapper running assembly in thread pool."""
        return await asyncio.to_thread(self.assemble_sync, line_entries, output_path)


audio_assembler = FFmpegAudioAssembler()

