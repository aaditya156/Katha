from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_active_user, get_db
from app.core.exceptions import AuthorizationFailedException, EntityNotFoundException
from app.eval.golden_dataset import GoldenTestCase, load_golden_dataset
from app.models.episode import Episode
from app.models.evaluation import BenchmarkExperiment, EvaluationRun
from app.models.series import Series
from app.models.user import User
from app.schemas.evaluation import (
    BenchmarkExperimentResponse,
    CalibrationReport,
    EvaluationResult,
    EvaluationRunResponse,
    EvaluationSummaryMetrics,
)
from app.services.evaluator import evaluator_service
from app.services.experiments import experiment_runner

router = APIRouter(prefix="/evaluations", tags=["Evaluations & Observability"])


@router.get("/golden-dataset", response_model=list[GoldenTestCase])
async def get_golden_dataset(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[GoldenTestCase]:
    """Retrieve curated multilingual golden dataset for audio drama benchmarking."""
    return load_golden_dataset()


@router.post("/episodes/{episode_id}/evaluate", response_model=EvaluationRunResponse, status_code=status.HTTP_201_CREATED)
async def evaluate_episode(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    model_name: str = Query(default="gemini-1.5-pro"),
    provider: str = Query(default="gemini"),
    mode: Literal["LIVE", "MOCK"] = Query(default="MOCK"),
) -> EvaluationRunResponse:
    """Evaluate an existing episode using the 7-dimensional LLM Judge and persist metric trace with user ownership."""
    from fastapi import HTTPException
    from app.core.exceptions import LLMProviderError
    from app.providers.factory import get_llm_provider
    from app.services.evaluator import LLMJudgeEvaluator

    episode = await db.scalar(select(Episode).where(Episode.id == episode_id))
    if not episode:
        raise EntityNotFoundException("Episode", episode_id)

    # Verify series ownership
    series = await db.scalar(select(Series).where(Series.id == episode.series_id))
    if not series or series.user_id != current_user.id:
        raise AuthorizationFailedException("Not authorized to evaluate episodes in another user's series.")

    script_content = episode.script or episode.title
    outline_content = episode.outline or episode.premise

    # Explicit provider construction; fails clearly in LIVE mode when credentials are missing
    try:
        judge_llm = get_llm_provider(provider_name=provider, model_name=model_name, mode=mode)
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to initialize evaluation provider '{provider}' in {mode} mode: {str(exc)}",
        ) from exc

    # Avoid sharing mutable provider state across concurrent requests
    judge_evaluator = LLMJudgeEvaluator(llm_provider=judge_llm)

    eval_result: EvaluationResult = await judge_evaluator.evaluate_script(
        script=str(script_content),
        outline=str(outline_content),
        model_name=model_name,
        provider_id=provider,
    )

    # Determine token usage classification from judge provider metadata
    last_usage = judge_llm.get_last_usage()
    token_usage_type = last_usage.usage_type if last_usage else ("ACTUAL" if mode == "LIVE" else "MOCK")

    run = EvaluationRun(
        user_id=current_user.id,
        series_id=episode.series_id,
        episode_id=episode.id,
        model_name=model_name,
        provider=provider,
        critic_enabled=True,
        retrieval_enabled=True,
        latency_ms=eval_result.latency_ms,
        prompt_tokens=eval_result.prompt_tokens,
        completion_tokens=eval_result.completion_tokens,
        token_usage_type=token_usage_type,
        estimated_cost_usd=eval_result.estimated_cost_usd,
        revision_count=0,
        tts_cache_hit_rate=None,  # Unmeasured in text evaluation; represented as None/unavailable
        generated_script_text=str(script_content),
        composite_score=eval_result.composite_score,
        character_consistency=eval_result.rubric.character_consistency.score,
        plot_coherence=eval_result.rubric.narrative_coherence.score,
        language_naturalness=eval_result.rubric.localization_quality.score,
        pacing=eval_result.rubric.dialogue_quality.score,
        safety=eval_result.rubric.safety.score,
        passed=eval_result.passed,
        verdict=eval_result.verdict,
        scores_json=eval_result.rubric.model_dump(),
        node_latencies_json={
            "evaluation_latency_ms": eval_result.latency_ms,
        },
        feedback=eval_result.rubric.overall_critique,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return EvaluationRunResponse.model_validate(run)


@router.get("/runs", response_model=list[EvaluationRunResponse])
async def list_evaluation_runs(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    model_name: str | None = Query(default=None),
    passed: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[EvaluationRunResponse]:
    """List historical evaluation runs with metric traces, restricted strictly to current user's runs."""
    stmt = (
        select(EvaluationRun)
        .where(EvaluationRun.user_id == current_user.id)
        .order_by(EvaluationRun.created_at.desc())
    )
    if model_name:
        stmt = stmt.where(EvaluationRun.model_name == model_name)
    if passed is not None:
        stmt = stmt.where(EvaluationRun.passed == passed)
    stmt = stmt.limit(limit)

    runs = (await db.scalars(stmt)).all()
    return [EvaluationRunResponse.model_validate(r) for r in runs]


@router.get("/summary", response_model=EvaluationSummaryMetrics)
async def get_evaluation_summary(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvaluationSummaryMetrics:
    """Aggregate quality, latency percentiles, cost, and reliability metrics across current user's runs."""
    runs = (await db.scalars(
        select(EvaluationRun).where(EvaluationRun.user_id == current_user.id)
    )).all()

    if not runs:
        return EvaluationSummaryMetrics(
            total_runs=0,
            pass_rate=1.0,
            avg_quality_score=0.0,
            dimension_averages={
                "character_consistency": 0.0,
                "plot_coherence": 0.0,
                "language_naturalness": 0.0,
                "pacing": 0.0,
                "safety": 0.0,
            },
            p50_latency_ms=0.0,
            p95_latency_ms=0.0,
            total_cost_usd=0.0,
            total_prompt_tokens=0,
            total_completion_tokens=0,
            avg_revision_count=0.0,
            avg_tts_cache_hit_rate=None,
            failure_taxonomy={},
        )

    n = len(runs)
    passes = sum(1 for r in runs if r.passed)
    latencies = sorted(r.latency_ms for r in runs)
    p50_idx = int(n * 0.5)
    p95_idx = min(n - 1, int(n * 0.95))

    dim_averages = {
        "character_consistency": round(sum(r.character_consistency for r in runs) / n, 2),
        "plot_coherence": round(sum(r.plot_coherence for r in runs) / n, 2),
        "language_naturalness": round(sum(r.language_naturalness for r in runs) / n, 2),
        "pacing": round(sum(r.pacing for r in runs) / n, 2),
        "safety": round(sum(r.safety for r in runs) / n, 2),
    }

    failure_tax: dict[str, int] = {}
    for r in runs:
        if not r.passed:
            if r.character_consistency < 3.0:
                failure_tax["character_persona_drift"] = failure_tax.get("character_persona_drift", 0) + 1
            if r.plot_coherence < 3.0:
                failure_tax["plot_contradiction"] = failure_tax.get("plot_contradiction", 0) + 1
            if r.language_naturalness < 3.0:
                failure_tax["unnatural_dialect"] = failure_tax.get("unnatural_dialect", 0) + 1
            if r.pacing < 3.0:
                failure_tax["pacing_bloat"] = failure_tax.get("pacing_bloat", 0) + 1
            if r.safety < 4.0:
                failure_tax["safety_warning"] = failure_tax.get("safety_warning", 0) + 1

    tts_rates = [r.tts_cache_hit_rate for r in runs if r.tts_cache_hit_rate is not None]
    avg_tts = round(sum(tts_rates) / len(tts_rates), 2) if tts_rates else None

    return EvaluationSummaryMetrics(
        total_runs=n,
        pass_rate=round(passes / n, 2),
        avg_quality_score=round(sum(r.composite_score for r in runs) / n, 2),
        dimension_averages=dim_averages,
        p50_latency_ms=round(latencies[p50_idx], 2),
        p95_latency_ms=round(latencies[p95_idx], 2),
        total_cost_usd=round(sum(r.estimated_cost_usd for r in runs), 4),
        total_prompt_tokens=sum(r.prompt_tokens for r in runs),
        total_completion_tokens=sum(r.completion_tokens for r in runs),
        avg_revision_count=round(sum(r.revision_count for r in runs) / n, 2),
        avg_tts_cache_hit_rate=avg_tts,
        failure_taxonomy=failure_tax,
    )


@router.post("/benchmark", response_model=BenchmarkExperimentResponse)
async def run_benchmark_experiment(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    experiment_type: Literal["critic_on_off", "rag_ablation", "model_comparison"] = Query(...),
    num_cases: int = Query(default=6, ge=1, le=35),
    model_a: str = Query(default="gemini-1.5-pro"),
    model_b: str = Query(default="gemini-1.5-flash"),
    provider_a: str | None = Query(default=None),
    provider_b: str | None = Query(default=None),
    judge_model: str = Query(default="gemini-1.5-pro"),
    judge_provider: str | None = Query(default=None),
    mode: Literal["LIVE", "MOCK"] = Query(default="MOCK"),
) -> BenchmarkExperimentResponse:
    """Execute a controlled benchmark experiment across golden premises."""
    from fastapi import HTTPException
    from app.core.config import get_settings
    settings = get_settings()

    # Fail fast if LIVE mode is requested without required credentials
    if mode == "LIVE":
        prov_a = provider_a or ("gemini" if "gemini" in model_a.lower() else "groq" if "groq" in model_a.lower() else "mock")
        prov_b = provider_b or ("gemini" if "gemini" in model_b.lower() else "groq" if "groq" in model_b.lower() else "mock")
        prov_judge = judge_provider or ("gemini" if "gemini" in judge_model.lower() else "groq" if "groq" in judge_model.lower() else "mock")

        for p_name, m_name in [(prov_a, model_a), (prov_b, model_b), (prov_judge, judge_model)]:
            if p_name == "gemini" and not settings.GEMINI_API_KEY:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing GEMINI_API_KEY required for LIVE experiment execution of model '{m_name}'."
                )
            if p_name == "groq" and not settings.GROQ_API_KEY:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing GROQ_API_KEY required for LIVE experiment execution of model '{m_name}'."
                )

    all_cases = load_golden_dataset()
    cases = all_cases[:num_cases]
    return await experiment_runner.run_experiment(
        experiment_type=experiment_type,
        test_cases=cases,
        model_a=model_a,
        model_b=model_b,
        provider_a=provider_a,
        provider_b=provider_b,
        judge_model=judge_model,
        judge_provider=judge_provider,
        mode=mode,
        user_id=current_user.id,
        db=db,
    )


@router.get("/calibration", response_model=CalibrationReport)
async def get_judge_calibration_report(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CalibrationReport:
    """Run calibration analysis against human ground-truth scripts (returns PENDING_HUMAN_ANNOTATION when empirical human annotations are pending)."""
    return await evaluator_service.run_calibration()


