"""Make tts_cache_hit_rate nullable in evaluation_runs for unmeasured text evaluations

Revision ID: 007_evaluation_tts_nullable
Revises: 006_evaluation_traceability
Create Date: 2026-11-23 11:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007_evaluation_tts_nullable"
down_revision: Union[str, None] = "006_evaluation_traceability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "evaluation_runs",
        "tts_cache_hit_rate",
        existing_type=sa.Float(),
        nullable=True,
    )


def downgrade() -> None:
    # Set existing NULL values to 0.0 before reverting to NOT NULL
    op.execute("UPDATE evaluation_runs SET tts_cache_hit_rate = 0.0 WHERE tts_cache_hit_rate IS NULL")
    op.alter_column(
        "evaluation_runs",
        "tts_cache_hit_rate",
        existing_type=sa.Float(),
        nullable=False,
        server_default=sa.text("0.0"),
    )
