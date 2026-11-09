from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.episode import EpisodeResponse


class SeriesBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    genre: str = Field(default="drama", max_length=100)
    logline: str = Field(..., min_length=10, max_length=2000)
    target_language: Literal["hindi", "hinglish", "english"] = "hindi"


class SeriesCreate(SeriesBase):
    pass


class SeriesUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    genre: str | None = Field(default=None, max_length=100)
    logline: str | None = Field(default=None, min_length=10, max_length=2000)
    target_language: Literal["hindi", "hinglish", "english"] | None = None
    status: str | None = Field(default=None, max_length=50)


class SeriesResponse(SeriesBase):
    model_config = ConfigDict(from_attributes=True, strict=True)

    id: str
    user_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class SeriesDetailResponse(SeriesResponse):
    episodes: list[EpisodeResponse] = Field(default_factory=list)

