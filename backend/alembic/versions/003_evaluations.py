"""Add evaluation_runs and benchmark_experiments tables

Revision ID: 003_evaluations
Revises: 002_story_bible
Create Date: 2026-11-10 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003_evaluations"
down_revision: Union[str, None] = "002_story_bible"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create evaluation_runs table
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("series_id", sa.String(length=36), nullable=True),
        sa.Column("episode_id", sa.String(length=36), nullable=True),
        sa.Column("test_case_id", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("critic_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("retrieval_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tts_cache_hit_rate", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("character_consistency", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("plot_coherence", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("language_naturalness", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("pacing", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("safety", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("verdict", sa.String(length=50), nullable=False, server_default=sa.text("'PASS'")),
        sa.Column("scores_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("node_latencies_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evaluation_runs_id"), "evaluation_runs", ["id"], unique=False)
    op.create_index(op.f("ix_evaluation_runs_series_id"), "evaluation_runs", ["series_id"], unique=False)
    op.create_index(op.f("ix_evaluation_runs_episode_id"), "evaluation_runs", ["episode_id"], unique=False)
    op.create_index(op.f("ix_evaluation_runs_test_case_id"), "evaluation_runs", ["test_case_id"], unique=False)

    # 2. Create benchmark_experiments table
    op.create_table(
        "benchmark_experiments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("experiment_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'COMPLETED'")),
        sa.Column("results_summary", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_benchmark_experiments_id"), "benchmark_experiments", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_benchmark_experiments_id"), table_name="benchmark_experiments")
    op.drop_table("benchmark_experiments")
    op.drop_index(op.f("ix_evaluation_runs_test_case_id"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_episode_id"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_series_id"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_id"), table_name="evaluation_runs")
    op.drop_table("evaluation_runs")

