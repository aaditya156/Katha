"""Add HNSW vector index and multilingual generated full-text search index for Story Bible

Revision ID: 004_story_bible_hybrid_indexes
Revises: 003_evaluations
Create Date: 2026-11-22 17:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_story_bible_hybrid_indexes"
down_revision: Union[str, None] = "003_evaluations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Ensure pgvector extension exists
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # 2. Create HNSW index for high-performance cosine similarity vector search
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_story_bible_embedding_hnsw
            ON story_bible_entries
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
            """
        )

        # 3. Add multilingual generated tsvector column (English + Simple for Hindi/Hinglish)
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

        # 4. Create GIN index on generated search_vector column
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_story_bible_search_vector
            ON story_bible_entries
            USING gin (search_vector);
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_story_bible_search_vector;")
        op.execute("ALTER TABLE story_bible_entries DROP COLUMN IF EXISTS search_vector;")
        op.execute("DROP INDEX IF EXISTS idx_story_bible_embedding_hnsw;")
