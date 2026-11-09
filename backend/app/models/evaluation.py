from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
from app.models.base import Base, TimestampMixin, UUIDMixin


class EvaluationRun(Base, UUIDMixin, TimestampMixin):
    """Stores individual LLM-as-a-judge evaluation runs and metric traces."""

    __tablename__ = "evaluation_runs"

    series_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    episode_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    test_case_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Provider & Model configuration
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    critic_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retrieval_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Observability & Resource metrics
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tts_cache_hit_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Evaluation quality scores (1.0 to 5.0 scale per AGENTS.md / Rubric)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    character_consistency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    plot_coherence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    language_naturalness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pacing: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    safety: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    passed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verdict: Mapped[str] = mapped_column(String(50), default="PASS", nullable=False)  # PASS, FAIL, MARGINAL

    # Detailed dimensional scores, node latencies, and qualitative critiques
    scores_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    node_latencies_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BenchmarkExperiment(Base, UUIDMixin, TimestampMixin):
    """Stores aggregate benchmark experiment results for model comparison, critic abaltion, or RAG ablation."""

    __tablename__ = "benchmark_experiments"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    experiment_type: Mapped[str] = mapped_column(String(50), nullable=False)  # critic_on_off, rag_ablation, model_comparison
    status: Mapped[str] = mapped_column(String(50), default="COMPLETED", nullable=False)
    results_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
