"""Add generated multilingual tsvector column and GIN index for Story Bible search

Revision ID: 005_story_bible_search_vector
Revises: 004_story_bible_hybrid_indexes
Create Date: 2026-11-22 17:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005_story_bible_search_vector"
down_revision: Union[str, None] = "004_story_bible_hybrid_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Add multilingual generated tsvector column (English + Simple)
        op.execute(
            """
            ALTER TABLE story_bible_entries
            ADD COLUMN IF NOT EXISTS search_vector tsvector
            GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(entity_name, '') || ' ' || coalesce(entity_type, '') || ' ' || coalesce(content, ''))
                || to_tsvector('simple', coalesce(entity_name, '') || ' ' || coalesce(entity_type, '') || ' ' || coalesce(content, ''))
            ) STORED;
            """
        )

        # 2. Create GIN index on search_vector column
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_story_bible_search_vector
            ON story_bible_entries
            USING gin (search_vector);
            """
        )

        # 3. Clean up legacy expression index if it exists
        op.execute("DROP INDEX IF EXISTS idx_story_bible_tsv_gin;")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_story_bible_search_vector;")
        op.execute("ALTER TABLE story_bible_entries DROP COLUMN IF EXISTS search_vector;")
        # Recreate legacy expression index for clean rollback to 004
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_story_bible_tsv_gin
            ON story_bible_entries
            USING gin (
                to_tsvector(
                    'english',
                    coalesce(entity_name, '') || ' ' || coalesce(entity_type, '') || ' ' || coalesce(content, '')
                )
            );
            """
        )
