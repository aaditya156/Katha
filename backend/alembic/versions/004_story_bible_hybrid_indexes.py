"""Add HNSW vector index and full-text search index for Story Bible hybrid retrieval

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

        # 3. Create GIN index for PostgreSQL Full-Text Search across entity_name, entity_type, and content
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


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_story_bible_tsv_gin;")
        op.execute("DROP INDEX IF EXISTS idx_story_bible_embedding_hnsw;")
