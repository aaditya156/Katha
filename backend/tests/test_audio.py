import os
from pathlib import Path
import wave
import pytest
from app.providers.tts.base import TTSProviderError
from app.providers.tts.mock import MockTTSProvider
from app.services.audio_assembler import FFmpegAudioAssembler
from app.services.audio_cache import AudioCacheService
from app.services.audio_orchestrator import AudioOrchestrationService


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "audio_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.mark.asyncio
async def test_tts_mock_synthesis_valid_audio() -> None:
    """Verify that TTS synthesis returns valid audio containers with > 100 bytes and valid headers."""
    tts = MockTTSProvider()
    audio_bytes = await tts.synthesize_line(
        text="Namaste, this is a test audio line.",
        voice_id="mock_m_kabir",
        line_id="line_001",
        speed=1.0,
        pitch=0.0,
        emotion="calm",
    )

    # Adheres to AGENTS.md audio validation rule: > 100 bytes
    assert len(audio_bytes) > 100
    # Must have valid RIFF WAVE header
    assert audio_bytes.startswith(b"RIFF")
    assert b"WAVE" in audio_bytes[:16]

    # Verify duration and sample rate via wave reader
    temp_wav = Path("test_sample.wav")
    temp_wav.write_bytes(audio_bytes)
    try:
        with wave.open(str(temp_wav), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getframerate() == 24000
            assert w.getnframes() > 0
            duration = w.getnframes() / float(w.getframerate())
            assert duration > 0.5
    finally:
        temp_wav.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_deterministic_audio_caching(temp_cache_dir: Path) -> None:
    """Verify that identical synthesis calls hit cache, while text/emotion changes trigger new synthesis."""
    cache = AudioCacheService(cache_dir=temp_cache_dir)
    tts = MockTTSProvider()

    # First call: Cache miss -> synthesizes and saves
    path_1, was_cached_1 = await cache.get_or_synthesize(
        text="Hello world dialogue",
        voice_id="mock_m_kabir",
        line_id="l1",
        tts=tts,
        emotion="neutral",
    )
    assert was_cached_1 is False
    assert path_1.exists()
    assert len(tts.synthesis_calls) == 1

    # Second call (identical): Cache hit -> returns cached file without calling TTS
    path_2, was_cached_2 = await cache.get_or_synthesize(
        text="Hello world dialogue",
        voice_id="mock_m_kabir",
        line_id="l1",
        tts=tts,
        emotion="neutral",
    )
    assert was_cached_2 is True
    assert path_1 == path_2
    assert len(tts.synthesis_calls) == 1  # No additional TTS call

    # Third call (emotion changed): Cache miss -> new fingerprint
    path_3, was_cached_3 = await cache.get_or_synthesize(
        text="Hello world dialogue",
        voice_id="mock_m_kabir",
        line_id="l1",
        tts=tts,
        emotion="furious",
    )
    assert was_cached_3 is False
    assert path_3 != path_1
    assert len(tts.synthesis_calls) == 2


@pytest.mark.asyncio
async def test_tts_provider_failure_modes() -> None:
    """Verify that TTS failures are never swallowed and raise structured TTSProviderError."""
    # 1. Timeout failure
    tts_timeout = MockTTSProvider(mode="timeout")
    with pytest.raises(TTSProviderError) as exc_1:
        await tts_timeout.synthesize_line("Text", "mock_m_kabir", line_id="line_err_1")
    assert exc_1.value.status_code == 502
    assert "timed out" in exc_1.value.detail
    assert exc_1.value.extras["line_id"] == "line_err_1"

    # 2. Quota / Rate limit failure
    tts_quota = MockTTSProvider(mode="quota_exceeded")
    with pytest.raises(TTSProviderError) as exc_2:
        await tts_quota.synthesize_line("Text", "mock_m_kabir", line_id="line_err_2")
    assert "quota exceeded" in exc_2.value.detail

    # 3. Corrupt output (< 100 bytes)
    tts_corrupt = MockTTSProvider(mode="corrupt_output")
    cache = AudioCacheService()
    with pytest.raises(ValueError) as exc_3:
        await cache.get_or_synthesize("Text", "mock_m_kabir", "line_err_3", tts=tts_corrupt)
    assert "smaller than 100 bytes minimum" in str(exc_3.value)


@pytest.mark.asyncio
async def test_audio_assembly_with_pauses_and_timeline(temp_cache_dir: Path) -> None:
    """Verify that FFmpeg/PCM assembler inserts 250ms inter-line and 800ms scene pauses, generating valid timeline manifest."""
    tts = MockTTSProvider()
    cache = AudioCacheService(cache_dir=temp_cache_dir)
    assembler = FFmpegAudioAssembler(inter_line_pause_ms=250, scene_pause_ms=800)

    # Synthesize two lines
    path_1, _ = await cache.get_or_synthesize("Line one dialogue", "mock_m_kabir", "l1", tts)
    path_2, _ = await cache.get_or_synthesize("Line two in next scene", "mock_f_ananya", "l2", tts)

    line_entries = [
        {"line_id": "l1", "character_name": "Kabir", "audio_path": path_1, "is_scene_break": True},
        {"line_id": "l2", "character_name": "Ananya", "audio_path": path_2, "is_scene_break": False},
    ]

    out_master = temp_cache_dir / "test_master.wav"
    master_path, timeline = await assembler.assemble_episode(line_entries, out_master)

    assert master_path.exists()
    assert master_path.stat().st_size > 500
    assert len(timeline) == 2

    # Verify timeline timestamps
    entry_1 = timeline[0]
    entry_2 = timeline[1]
    assert entry_1["line_id"] == "l1"
    assert entry_1["start_seconds"] == 0.0
    assert entry_1["end_seconds"] > 0.0

    # Entry 2 should start after entry 1's end + scene pause (800ms)
    expected_start_2 = round(entry_1["end_seconds"] + 0.8, 3)
    assert abs(entry_2["start_seconds"] - expected_start_2) < 0.05
    assert entry_2["end_seconds"] > entry_2["start_seconds"]


@pytest.mark.asyncio
async def test_per_line_regeneration_efficiency(temp_cache_dir: Path) -> None:
    """Verify that regenerating a single line synthesizes ONLY that line, reusing cached audio for all untouched lines."""
    cache = AudioCacheService(cache_dir=temp_cache_dir)
    tts = MockTTSProvider()
    assembler = FFmpegAudioAssembler()

    # Initial state with 3 lines
    lines = [
        {"line_id": "l1", "character_name": "Kabir", "text": "First dialogue", "voice_id": "mock_m_kabir"},
        {"line_id": "l2", "character_name": "Ananya", "text": "Second dialogue", "voice_id": "mock_f_ananya"},
        {"line_id": "l3", "character_name": "The Caller", "text": "Third dialogue", "voice_id": "mock_m_elder"},
    ]

    initial_entries = []
    for l in lines:
        p, _ = await cache.get_or_synthesize(l["text"], l["voice_id"], l["line_id"], tts)
        initial_entries.append({"line_id": l["line_id"], "character_name": l["character_name"], "audio_path": p, "is_scene_break": False})

    master_path_1, _ = await assembler.assemble_episode(initial_entries, temp_cache_dir / "master_v1.wav")
    assert len(tts.synthesis_calls) == 3

    # Now simulate per-line regeneration of Line 2 with updated text
    lines[1]["text"] = "Second dialogue modified by author"

    # Only line 2 should trigger a new synthesis call
    new_entries = []
    for l in lines:
        p, was_cached = await cache.get_or_synthesize(l["text"], l["voice_id"], l["line_id"], tts)
        new_entries.append({"line_id": l["line_id"], "character_name": l["character_name"], "audio_path": p, "is_scene_break": False})

    # Exactly 1 new synthesis call made (for line 2)! Total calls = 4 (3 initial + 1 new)
    assert len(tts.synthesis_calls) == 4
    # Re-assemble master
    master_path_2, timeline_2 = await assembler.assemble_episode(new_entries, temp_cache_dir / "master_v2.wav")
    assert master_path_2.exists()
    assert len(timeline_2) == 3
