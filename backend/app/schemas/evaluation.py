from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class DimensionScore(BaseModel):
    model_config = ConfigDict(strict=True)

    score: float = Field(..., ge=1.0, le=5.0, description="Numerical rating on strict 1 to 5 rubric scale")
    reasoning: str = Field(..., description="Detailed analytical justification citing specific lines or beats")
    evidence: list[str] = Field(default_factory=list, description="Direct quotes or concrete structural flaws")


class EvaluationRubricOutput(BaseModel):
    """Structured Pydantic LLM Judge Evaluation Rubric (1–5 scale)."""

    model_config = ConfigDict(strict=True)

    character_consistency: DimensionScore = Field(
        ...,
        description="Vocal archetype stability, emotional logic, and personality continuity",
    )
    plot_coherence: DimensionScore = Field(
        ...,
        description="Logical cause-and-effect, absence of plot holes, and clear dramatic stakes",
    )
    language_naturalness: DimensionScore = Field(
        ...,
        description="Authenticity of idiom, colloquial cadence (Hindi/Hinglish/English), and subtext",
    )
    pacing: DimensionScore = Field(
        ...,
        description="Scene momentum, rhythm, acoustic soundscape cues, and lack of dialogue bloat",
    )
    safety: DimensionScore = Field(
        ...,
        description="Compliance with content safety, absence of uncontextualized hate speech or harassment",
    )
    overall_critique: str = Field(..., description="Executive critique summary with concrete guidance")


class EvaluationResult(BaseModel):
    model_config = ConfigDict(strict=True)

    composite_score: float = Field(..., ge=1.0, le=5.0)
    passed: bool
    verdict: Literal["PASS", "FAIL", "MARGINAL"]
    rubric: EvaluationRubricOutput
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0


class HumanLabeledSample(BaseModel):
    """Ground-truth human expert labeled script for judge calibration."""

    model_config = ConfigDict(strict=True)

    sample_id: str
    title: str
    target_language: str
    genre: str
    human_scores: dict[str, float]  # character_consistency, plot_coherence, language_naturalness, pacing, safety, composite
    judge_scores: dict[str, float] | None = None
    human_notes: str = ""


class CalibrationReport(BaseModel):
    """Statistical calibration report assessing LLM judge alignment with human ground truth."""

    model_config = ConfigDict(strict=True)

    total_samples: int
    spearman_correlation: dict[str, float]  # rho per dimension & composite
    weighted_cohens_kappa: dict[str, float]  # quadratic weighted kappa per dimension
    mean_absolute_error: dict[str, float]  # MAE per dimension
    identified_weaknesses: list[str]
    recommendations: list[str]
    calibration_status: Literal["EXCELLENT", "ACCEPTABLE", "NEEDS_TUNING"]


class ExperimentVariantMetrics(BaseModel):
    model_config = ConfigDict(strict=True)

    variant_name: str
    sample_count: int
    avg_composite_score: float
    avg_character_consistency: float
    avg_plot_coherence: float
    avg_language_naturalness: float
    avg_pacing: float
    avg_safety: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_tokens: int
    avg_cost_usd: float
    pass_rate: float
    revision_rate: float
    tts_cache_hit_rate: float


class BenchmarkExperimentResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    experiment_id: str
    experiment_type: Literal["critic_on_off", "rag_ablation", "model_comparison"]
    title: str
    variants: list[ExperimentVariantMetrics]
    delta_analysis: dict[str, Any]
    created_at: str


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)

    id: str
    series_id: str | None = None
    episode_id: str | None = None
    test_case_id: str | None = None
    model_name: str
    provider: str
    critic_enabled: bool
    retrieval_enabled: bool
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    revision_count: int
    tts_cache_hit_rate: float
    composite_score: float
    character_consistency: float
    plot_coherence: float
    language_naturalness: float
    pacing: float
    safety: float
    passed: bool
    verdict: str
    scores_json: dict[str, Any]
    node_latencies_json: dict[str, Any]
    feedback: str
    created_at: datetime


class EvaluationSummaryMetrics(BaseModel):
    model_config = ConfigDict(strict=True)

    total_runs: int
    pass_rate: float
    avg_quality_score: float
    dimension_averages: dict[str, float]
    p50_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    avg_revision_count: float
    avg_tts_cache_hit_rate: float
    failure_taxonomy: dict[str, int]  # breakdown of failures: low_coherence, safety_violation, unnatural_dialect, etc.

