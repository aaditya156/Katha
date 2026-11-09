from typing import Any, TYPE_CHECKING
import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator
from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.series import Series


class SafeVector(TypeDecorator):
    """Dialect-safe Vector type: uses native pgvector.Vector(768) on PostgreSQL and JSON on SQLite."""

    impl = sa.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: sa.engine.Dialect) -> sa.types.TypeEngine[Any]:
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector
                return dialect.type_descriptor(Vector(768))
            except ImportError:
                return dialect.type_descriptor(sa.JSON())
        return dialect.type_descriptor(sa.JSON())


class StoryBibleEntry(Base, UUIDMixin, TimestampMixin):
    """Stores episodic world lore, characters, relationship graphs, and open plot threads."""

    __tablename__ = "story_bible_entries"

    series_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    episode_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # character, relationship, location, event, open_plot_thread, rule

    entity_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON,
        nullable=False,
        default=dict,
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        SafeVector,
        nullable=True,
    )

    # Relationship
    series: Mapped["Series"] = relationship("Series", back_populates="story_bible_entries")
