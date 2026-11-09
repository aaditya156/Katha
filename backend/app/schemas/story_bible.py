from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class CharacterFact(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(..., description="Character name")
    traits: list[str] = Field(default_factory=list, description="Core personality quirks and flaws")
    vocal_traits: str = Field(default="", description="Acoustic vocal texture and speaking speed")
    current_state: str = Field(default="", description="Psychological or narrative state at episode close")


class RelationshipFact(BaseModel):
    model_config = ConfigDict(strict=True)

    character_a: str
    character_b: str
    dynamic: str = Field(..., description="Nature of conflict, alliance, romance, or rivalry")
    status: str = Field(default="active", description="Status of connection")


class LocationFact(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    atmosphere_soundscape: str = Field(..., description="Signature acoustic bed and background audio cues")
    significance: str = Field(..., description="Dramatic or historical importance in the world")


class EventFact(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str
    description: str
    characters_involved: list[str] = Field(default_factory=list)


class PlotThreadFact(BaseModel):
    model_config = ConfigDict(strict=True)

    thread_id: str
    description: str = Field(..., description="Unresolved hook, mystery, or promise to listener")
    status: Literal["open", "resolved", "unresolved_hook"] = "open"


class StoryBibleExtraction(BaseModel):
    """Structured facts extracted by Bible Updater from a finalized episode."""

    model_config = ConfigDict(strict=True)

    characters: list[CharacterFact] = Field(default_factory=list)
    relationships: list[RelationshipFact] = Field(default_factory=list)
    locations: list[LocationFact] = Field(default_factory=list)
    events: list[EventFact] = Field(default_factory=list)
    open_plot_threads: list[PlotThreadFact] = Field(default_factory=list)
    episode_synopsis: str = Field(..., description="High-level narrative summary of this episode")


class StoryBibleEntryCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    entity_type: str = Field(..., description="character, relationship, location, event, open_plot_thread, rule")
    entity_name: str
    content: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class StoryBibleEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)

    id: str
    series_id: str
    episode_id: str | None = None
    entity_type: str
    entity_name: str
    content: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class StoryBibleSearchResult(BaseModel):
    model_config = ConfigDict(strict=True)

    entry: StoryBibleEntryResponse
    score: float = Field(..., ge=0.0, le=1.0)
    retrieval_method: str = Field(..., description="dense, sparse, or hybrid")


class StoryBibleSearchRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    query: str = Field(..., min_length=1, description="Search query or episode premise")
    limit: int = Field(default=5, ge=1, le=20)
    retrieval_enabled: bool | None = Field(default=None, description="Ablation flag override")


class StoryBibleSearchResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    status: Literal["RETRIEVAL_SUCCESS", "RETRIEVAL_EMPTY", "RETRIEVAL_DISABLED"]
    query: str
    results: list[StoryBibleSearchResult] = Field(default_factory=list)
    retrieval_enabled: bool = True
