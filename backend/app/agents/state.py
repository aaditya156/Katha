from operator import add
from typing import Annotated, Any, TypedDict
from app.schemas.outline import EpisodeOutline
from app.schemas.script import (
    BibleUpdatePayload,
    CastScript,
    CritiqueReport,
    GraphErrorRecord,
    LocalizedScript,
    Script,
)
from app.schemas.story_bible import StoryBibleExtraction


class KathaEpisodeState(TypedDict, total=False):
    """The central typed state passed across all agent nodes in Katha Studio."""

    # Episode metadata
    series_id: str
    episode_id: str
    episode_number: int
    premise: str
    target_language: str
    target_duration_minutes: int
    genre: str
    characters_hint: list[str] | None

    # Pipeline artifacts
    outline: EpisodeOutline | None
    raw_script: Script | None

    # Revisions & Quality Loop
    critique_history: Annotated[list[CritiqueReport], add]
    current_critique: CritiqueReport | None
    critic_score: float
    revision_count: int
    failing_scenes: list[int]  # Specific scene numbers that failed review and must be rewritten

    # Downstream artifacts
    localized_script: LocalizedScript | None
    cast_script: CastScript | None
    bible_updates: BibleUpdatePayload | None
    story_bible_extraction: StoryBibleExtraction | None

    # Graph Lifecycle & Reliability
    status: str  # PENDING, PLANNING, WRITING, CRITIQUING, REVISING, LOCALIZING, CASTING, UPDATING_BIBLE, COMPLETED, FAILED
    current_node: str
    errors: Annotated[list[GraphErrorRecord], add]
    simulation_flags: dict[str, Any]  # Used for testing forced mid-run failures & recovery

