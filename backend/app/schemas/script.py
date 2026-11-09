from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ScriptLine(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str = Field(..., description="Unique line identifier")
    line_number: int = Field(..., ge=1, description="Sequential line index in scene")
    character_name: str = Field(..., description="Speaking character or 'NARRATOR'")
    text: str = Field(..., min_length=1, description="Spoken dialogue text")
    stage_direction: str = Field(default="", description="Acoustic action, physical movement, or delivery tone")
    emotion: str = Field(default="neutral", description="Emotional inflection (e.g. whispered, trembling, furious)")
    pace: str = Field(default="normal", description="Speaking speed: slow, normal, or fast")
    voice_id: str | None = Field(default=None, description="Assigned voice synthesis ID")


class ScriptScene(BaseModel):
    model_config = ConfigDict(strict=True)

    scene_number: int = Field(..., ge=1)
    heading: str = Field(..., description="Audio scene heading (e.g. INT. RADIO STATION - NIGHT)")
    atmosphere_soundscape: str = Field(..., description="Background soundbed and sound effects")
    dramatic_objective: str = Field(..., description="What the scene accomplishes in the narrative")
    characters_present: list[str] = Field(..., min_length=1)
    lines: list[ScriptLine] = Field(..., min_length=1)


class Script(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str = Field(..., description="Script title")
    scenes: list[ScriptScene] = Field(..., min_length=1)
    total_lines: int = Field(..., ge=1)


class SceneCritique(BaseModel):
    model_config = ConfigDict(strict=True)

    scene_number: int = Field(..., ge=1)
    passed: bool = Field(..., description="True if scene meets dramatic quality standards")
    score: float = Field(..., ge=1.0, le=10.0, description="Scene dramatic quality score")
    issues: list[str] = Field(default_factory=list, description="Specific dramatic or dialogue flaws")
    suggested_improvements: str = Field(default="", description="Targeted guidance for rewriting this scene")


class CritiqueReport(BaseModel):
    model_config = ConfigDict(strict=True)

    score: float = Field(..., ge=1.0, le=10.0, description="Overall weighted score across all criteria")
    passed: bool = Field(..., description="Whether script passes review without revision")
    consistency_score: float = Field(..., ge=1.0, le=10.0)
    coherence_score: float = Field(..., ge=1.0, le=10.0)
    naturalness_score: float = Field(..., ge=1.0, le=10.0)
    pacing_score: float = Field(..., ge=1.0, le=10.0)
    safety_score: float = Field(..., ge=1.0, le=10.0)
    scene_critiques: list[SceneCritique] = Field(..., min_length=1)
    failing_scene_numbers: list[int] = Field(default_factory=list, description="Numbers of scenes needing rewrite")
    feedback: str = Field(..., description="High-level narrative review summary")


class LocalizedLine(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str
    line_number: int
    character_name: str
    text_original: str
    text_localized: str
    dialect_notes: str = ""
    emotion: str = "neutral"
    pace: str = "normal"
    voice_id: str | None = None


class LocalizedScene(BaseModel):
    model_config = ConfigDict(strict=True)

    scene_number: int
    heading: str
    atmosphere_soundscape: str
    lines: list[LocalizedLine]


class LocalizedScript(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str
    target_language: str
    scenes: list[LocalizedScene]
    total_lines: int


class VoiceAssignment(BaseModel):
    model_config = ConfigDict(strict=True)

    character_name: str
    voice_id: str
    provider: str
    gender: str
    vocal_archetype: str
    speed: float = 1.0
    pitch: float = 0.0


class CastScript(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str
    target_language: str
    cast: list[VoiceAssignment]
    scenes: list[LocalizedScene]
    total_lines: int


class CharacterLoreUpdate(BaseModel):
    model_config = ConfigDict(strict=True)

    character_name: str
    trait_evolutions: list[str] = Field(default_factory=list)
    relationship_shifts: list[str] = Field(default_factory=list)


class BibleUpdatePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    episode_number: int
    episode_summary: str
    cliffhanger_or_resolution: str
    character_updates: list[CharacterLoreUpdate] = Field(default_factory=list)
    new_world_lore: list[str] = Field(default_factory=list)


class GraphErrorRecord(BaseModel):
    model_config = ConfigDict(strict=True)

    node: str
    error: str
    timestamp: str
    recoverable: bool = True
