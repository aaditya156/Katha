"""Add experiment traceability and user ownership to evaluation_runs and benchmark_experiments

Revision ID: 006_evaluation_traceability
Revises: 005_story_bible_search_vector
Create Date: 2026-11-22 23:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006_evaluation_traceability"
down_revision: Union[str, None] = "005_story_bible_search_vector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update evaluation_runs with experiment linkage, usage type, generated text, and ownership
    op.add_column("evaluation_runs", sa.Column("experiment_id", sa.String(length=36), nullable=True))
    op.add_column("evaluation_runs", sa.Column("variant_name", sa.String(length=100), nullable=True))
    op.add_column("evaluation_runs", sa.Column("token_usage_type", sa.String(length=20), nullable=False, server_default=sa.text("'ESTIMATED'")))
    op.add_column("evaluation_runs", sa.Column("generated_script_text", sa.Text(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("user_id", sa.String(length=36), nullable=True))

    op.create_index(op.f("ix_evaluation_runs_experiment_id"), "evaluation_runs", ["experiment_id"], unique=False)
    op.create_index(op.f("ix_evaluation_runs_user_id"), "evaluation_runs", ["user_id"], unique=False)
    op.create_foreign_key("fk_evaluation_runs_experiment_id", "evaluation_runs", "benchmark_experiments", ["experiment_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_evaluation_runs_user_id", "evaluation_runs", "users", ["user_id"], ["id"], ondelete="CASCADE")

    # 2. Update benchmark_experiments with user ownership
    op.add_column("benchmark_experiments", sa.Column("user_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_benchmark_experiments_user_id"), "benchmark_experiments", ["user_id"], unique=False)
    op.create_foreign_key("fk_benchmark_experiments_user_id", "benchmark_experiments", "users", ["user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_benchmark_experiments_user_id", "benchmark_experiments", type_="foreignkey")
    op.drop_index(op.f("ix_benchmark_experiments_user_id"), table_name="benchmark_experiments")
    op.drop_column("benchmark_experiments", "user_id")

    op.drop_constraint("fk_evaluation_runs_user_id", "evaluation_runs", type_="foreignkey")
    op.drop_constraint("fk_evaluation_runs_experiment_id", "evaluation_runs", type_="foreignkey")
    op.drop_index(op.f("ix_evaluation_runs_user_id"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_experiment_id"), table_name="evaluation_runs")
    op.drop_column("evaluation_runs", "user_id")
    op.drop_column("evaluation_runs", "generated_script_text")
    op.drop_column("evaluation_runs", "token_usage_type")
    op.drop_column("evaluation_runs", "variant_name")
    op.drop_column("evaluation_runs", "experiment_id")
