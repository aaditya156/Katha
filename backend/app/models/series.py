from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.episode import Episode
    from app.models.series import Series
    from app.models.story_bible import StoryBibleEntry
    from app.models.user import User


class Series(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "series"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    genre: Mapped[str] = mapped_column(String(100), nullable=False, default="drama")
    logline: Mapped[str] = mapped_column(Text, nullable=False)
    target_language: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="hindi",
    )  # hindi, hinglish, english
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="series")
    episodes: Mapped[list["Episode"]] = relationship(
        "Episode",
        back_populates="series",
        cascade="all, delete-orphan",
        order_by="Episode.episode_number",
    )
    story_bible_entries: Mapped[list["StoryBibleEntry"]] = relationship(
        "StoryBibleEntry",
        back_populates="series",
        cascade="all, delete-orphan",
    )

