"""Add partial unique index on active background jobs

Revision ID: 009_active_job_unique_index
Revises: 008_background_jobs
Create Date: 2026-11-23 12:35:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009_active_job_unique_index"
down_revision: Union[str, None] = "008_background_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the non-unique composite index from migration 008 if present
    try:
        op.drop_index("ix_background_jobs_episode_active", table_name="background_jobs")
    except Exception:
        pass

    # Create partial unique index guaranteeing only one active generation job per episode
    op.create_index(
        "uq_active_generation_job",
        "background_jobs",
        ["episode_id", "job_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING', 'RETRYING')"),
        sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING', 'RETRYING')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_generation_job", table_name="background_jobs")
    op.create_index(
        "ix_background_jobs_episode_active",
        "background_jobs",
        ["episode_id", "job_type", "status"],
    )
