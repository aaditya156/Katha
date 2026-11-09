from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.outline import EpisodeOutline


class EpisodeBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    premise: str = Field(..., min_length=10, max_length=2000)
    episode_number: int = Field(default=1, ge=1)
    target_language: Literal["hindi", "hinglish", "english"] = "hindi"
    duration_minutes_target: int = Field(default=5, ge=1, le=30)


class EpisodeCreate(EpisodeBase):
    series_id: str


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    premise: str | None = Field(default=None, min_length=10, max_length=2000)
    episode_number: int | None = Field(default=None, ge=1)
    status: str | None = None
    outline: dict[str, Any] | None = None
    script: dict[str, Any] | None = None
    audio_url: str | None = None


class EpisodeResponse(EpisodeBase):
    model_config = ConfigDict(from_attributes=True, strict=True)

    id: str
    series_id: str
    status: str
    outline: dict[str, Any] | None = None
    script: dict[str, Any] | None = None
    audio_url: str | None = None
    created_at: datetime
    updated_at: datetime

