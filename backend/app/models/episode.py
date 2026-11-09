from typing import Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.series import Series


class Episode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "episodes"

    series_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    premise: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="DRAFT",
    )  # DRAFT, OUTLINE_GENERATED, WRITING, REVISING, LOCALIZED, READY, FAILED
    target_language: Mapped[str] = mapped_column(String(50), nullable=False, default="hindi")
    duration_minutes_target: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Structured JSON artifacts
    outline: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    script: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Relationships
    series: Mapped["Series"] = relationship("Series", back_populates="episodes")
