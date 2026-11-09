"""Add story_bible_entries table with pgvector support

Revision ID: 002_story_bible
Revises: 001_initial_schema
Create Date: 2026-11-10 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from app.models.story_bible import SafeVector

revision: str = "002_story_bible"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create story_bible_entries table
    op.create_table(
        "story_bible_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("series_id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("embedding", SafeVector(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_story_bible_entries_id"), "story_bible_entries", ["id"], unique=False)
    op.create_index(op.f("ix_story_bible_entries_series_id"), "story_bible_entries", ["series_id"], unique=False)
    op.create_index(op.f("ix_story_bible_entries_episode_id"), "story_bible_entries", ["episode_id"], unique=False)
    op.create_index(op.f("ix_story_bible_entries_entity_type"), "story_bible_entries", ["entity_type"], unique=False)
    op.create_index(op.f("ix_story_bible_entries_entity_name"), "story_bible_entries", ["entity_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_story_bible_entries_entity_name"), table_name="story_bible_entries")
    op.drop_index(op.f("ix_story_bible_entries_entity_type"), table_name="story_bible_entries")
    op.drop_index(op.f("ix_story_bible_entries_episode_id"), table_name="story_bible_entries")
    op.drop_index(op.f("ix_story_bible_entries_series_id"), table_name="story_bible_entries")
    op.drop_index(op.f("ix_story_bible_entries_id"), table_name="story_bible_entries")
    op.drop_table("story_bible_entries")
