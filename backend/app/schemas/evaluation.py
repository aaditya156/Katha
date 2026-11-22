from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field


class DimensionScore(BaseModel):
    model_config = ConfigDict(strict=True)

    score: float = Field(..., ge=1.0, le=5.0, description="Numerical rating on strict 1 to 5 rubric scale")
    reasoning: str = Field(..., description="Detailed analytical justification citing specific lines or beats")
    evidence: list[str] = Field(default_factory=list, description="Direct quotes or concrete structural flaws/omissions")


class EvaluationRubricOutput(BaseModel):
    """Structured Pydantic LLM Judge Evaluation Rubric across 7 rigorous dimensions (1–5 scale)."""

    model_config = ConfigDict(strict=True)

    # 1. Narrative Coherence
    narrative_coherence: DimensionScore = Field(
        ...,
        description="Logical cause-and-effect progression, dramatic causality, and clarity of narrative stakes",
    )
    # 2. Character Consistency
    character_consistency: DimensionScore = Field(
        ...,
        description="Vocal archetype stability, emotional logic, and personality continuity across all scenes",
    )
    # 3. Dialogue Quality
    dialogue_quality: DimensionScore = Field(
        ...,
        description="Subtext, acoustic rhythm, natural dialogue length without monologue bloat, and audio pacing",
    )
    # 4. Plot Continuity
    plot_continuity: DimensionScore = Field(
        ...,
        description="Adherence to established story memory, absence of world-lore contradictions, and resolution of plot threads",
    )
    # 5. Localization Quality
    localization_quality: DimensionScore = Field(
        ...,
        description="Authenticity of idiom, culturally grounded colloquial cadence (Hindi/Hinglish/English), and natural code-switching",
    )
    # 6. Instruction Adherence
    instruction_adherence: DimensionScore = Field(
        ...,
        description="Strict compliance with prompt, outline beats, required duration, and cast constraints without silent omission",
    )
    # 7. Safety
    safety: DimensionScore = Field(
        ...,
        description="Compliance with broadcast safety policies, zero uncontextualized hate speech, harassment, or gratuitous violence",
    )

    overall_critique: str = Field(..., description="Executive critique summary with concrete guidance")
    rubric_version: str = Field(default="2.0.0", description="Evaluation rubric version identifier")

    # Backward compatibility properties for pre-existing endpoints and frontend UI
    @computed_field  # type: ignore[prop-decorator]
    @property
    def plot_coherence(self) -> DimensionScore:
        return self.narrative_coherence

    @computed_field  # type: ignore[prop-decorator]
    @property
    def language_naturalness(self) -> DimensionScore:
        return self.localization_quality

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pacing(self) -> DimensionScore:
        return self.dialogue_quality


class EvaluationResult(BaseModel):
    model_config = ConfigDict(strict=True)

    composite_score: float = Field(..., ge=1.0, le=5.0)
    passed: bool
    verdict: Literal["PASS", "FAIL", "MARGINAL"]
    rubric: EvaluationRubricOutput
    rubric_version: str = "2.0.0"
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_status: Literal["ESTIMATED", "UNKNOWN", "MOCK"] = "ESTIMATED"


class HumanEvaluationRecord(BaseModel):
    """Manually evaluated ground-truth record from a human expert annotator."""

    model_config = ConfigDict(strict=True)

    evaluator_id: str = Field(..., description="Anonymized ID of expert human annotator (e.g. 'annotator_expert_01')")
    rubric_version: str = Field(default="2.0.0", description="Rubric version evaluated against")
    evaluated_at: str = Field(..., description="ISO 8601 timestamp of human annotation")
    dimension_scores: dict[str, float] = Field(..., description="Scores for the 7 dimensions (1.0 to 5.0)")
    dimension_rationales: dict[str, str] = Field(..., description="Specific rationales and evidence cited by annotator")
    composite_score: float = Field(..., ge=1.0, le=5.0)
    is_verified: bool = Field(default=True, description="Whether rating has passed inter-annotator review")


class HumanLabeledSample(BaseModel):
    """Ground-truth human expert labeled script structure for judge calibration."""

    model_config = ConfigDict(strict=True)

    sample_id: str
    test_case_id: str = ""
    title: str
    target_language: str
    genre: str
    reference_script: str = ""
    is_synthetic: bool = Field(default=False, description="True for synthetic fixtures, False for real human ground truth")
    annotation_status: Literal["COMPLETED", "PENDING_HUMAN_ANNOTATION", "SYNTHETIC_FIXTURE"] = "PENDING_HUMAN_ANNOTATION"
    human_evaluation: HumanEvaluationRecord | None = None
    human_scores: dict[str, float] = Field(default_factory=dict)
    judge_scores: dict[str, float] | None = None
    human_notes: str = ""


class CalibrationReport(BaseModel):
    """Statistical calibration report assessing LLM judge alignment with human ground truth."""

    model_config = ConfigDict(strict=True)

    total_samples: int
    rubric_version: str = "2.0.0"
    is_empirical: bool = Field(default=False, description="True if calibrated against real human ground truth; False for synthetic fixtures")
    calibration_status: Literal["EXCELLENT", "ACCEPTABLE", "NEEDS_TUNING", "PENDING_HUMAN_ANNOTATION", "SYNTHETIC_TEST_ONLY"]
    spearman_correlation: dict[str, float]  # rho per dimension & composite
    weighted_cohens_kappa: dict[str, float | None]  # quadratic weighted kappa per dimension (None if assumptions violated)
    mean_absolute_error: dict[str, float]  # MAE per dimension
    identified_weaknesses: list[str]
    recommendations: list[str]


class ExperimentVariantMetrics(BaseModel):
    model_config = ConfigDict(strict=True)

    variant_name: str
    sample_count: int
    avg_composite_score: float
    # 7 Core Dimensions
    avg_narrative_coherence: float
    avg_character_consistency: float
    avg_dialogue_quality: float
    avg_plot_continuity: float
    avg_localization_quality: float
    avg_instruction_adherence: float
    avg_safety: float
    # Backward compatibility fields
    avg_plot_coherence: float
    avg_language_naturalness: float
    avg_pacing: float
    # Observability & Cost
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_tokens: int
    avg_cost_usd: float
    cost_status: str = "ESTIMATED"
    pass_rate: float
    failure_rate: float = 0.0
    revision_rate: float = 0.0
    validation_failures: int = 0
    tts_cache_hit_rate: float = 0.85


class BenchmarkExperimentResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    experiment_id: str
    experiment_type: Literal["critic_on_off", "rag_ablation", "model_comparison"]
    title: str
    dataset_version: str = "2.0.0"
    rubric_version: str = "2.0.0"
    prompt_version: str = "2.0.0"
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
    failure_taxonomy: dict[str, int]


