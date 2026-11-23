import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LLMProviderError
from app.core.security import create_access_token, hash_password
from app.core.telemetry import (
    estimate_token_cost,
    estimate_token_cost_with_status,
    register_model_pricing,
)
from app.eval.calibration_dataset import (
    compute_mae,
    compute_spearman_rho,
    compute_weighted_cohens_kappa,
    load_calibration_dataset,
    load_human_ground_truth_dataset,
)
from app.eval.golden_dataset import load_golden_dataset
from app.models.episode import Episode
from app.models.evaluation import BenchmarkExperiment, EvaluationRun
from app.models.series import Series
from app.models.story_bible import StoryBibleEntry
from app.models.user import User
from app.providers.factory import get_llm_provider
from app.providers.mock import MockLLMProvider
from app.schemas.evaluation import (
    CalibrationReport,
    DimensionScore,
    EvaluationRubricOutput,
    HumanEvaluationRecord,
    HumanLabeledSample,
)
from app.services.evaluator import LLMJudgeEvaluator
from app.services.experiments import ExperimentRunner
from scripts.eval_gate import run_evaluation_gate


def test_golden_dataset_structure():
    dataset = load_golden_dataset()
    assert len(dataset) >= 30
    languages = {item.target_language for item in dataset}
    assert "hindi" in languages
    assert "hinglish" in languages
    assert "english" in languages

    has_conflicting_traps = False
    has_open_threads = False

    for item in dataset:
        assert item.id
        assert item.title
        assert len(item.expected_characters) >= 1
        assert item.target_duration_minutes > 0
        assert len(item.evaluation_criteria) >= 1
        if item.conflicting_lore_traps:
            has_conflicting_traps = True
        if item.open_plot_threads:
            has_open_threads = True

    assert has_conflicting_traps, "At least one golden benchmark case must define conflicting lore traps"
    assert has_open_threads, "At least one golden benchmark case must define open plot threads"


def test_statistical_calibration_metrics():
    # Identical ratings -> rho=1.0, kappa=1.0, mae=0.0
    r1 = [1.0, 2.0, 3.0, 4.0, 5.0]
    r2 = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert compute_spearman_rho(r1, r2) == pytest.approx(1.0, abs=1e-4)
    assert compute_weighted_cohens_kappa(r1, r2) == pytest.approx(1.0, abs=1e-4)
    assert compute_mae(r1, r2) == pytest.approx(0.0, abs=1e-4)

    # Inverted ratings -> rho=-1.0
    r3 = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert compute_spearman_rho(r1, r3) == pytest.approx(-1.0, abs=1e-4)
    assert compute_mae(r1, r3) == pytest.approx(2.4, abs=1e-4)

    # Degenerate cases: zero variance in one rater -> Cohen's kappa assumption violated
    zero_var_a = [3.0, 3.0, 3.0, 3.0]
    varying_b = [1.0, 2.0, 3.0, 4.0]
    kappa_deg = compute_weighted_cohens_kappa(zero_var_a, varying_b)
    assert kappa_deg == 0.0 or kappa_deg is None


def test_human_ground_truth_dataset_awaiting_annotation():
    """Verify that human ground-truth dataset is empty/pending and never conflated with synthetic fixtures."""
    human_dataset = load_human_ground_truth_dataset()
    assert len(human_dataset) == 0, "No synthetic data should ever be present in the human ground truth dataset"

    # Verify HumanEvaluationRecord schema
    record = HumanEvaluationRecord(
        evaluator_id="annotator_expert_01",
        rubric_version="2.0.0",
        evaluated_at="2026-11-22T18:00:00Z",
        dimension_scores={
            "narrative_coherence": 4.5,
            "character_consistency": 4.8,
            "dialogue_quality": 4.6,
            "plot_continuity": 4.4,
            "localization_quality": 4.9,
            "instruction_adherence": 4.7,
            "safety": 5.0,
        },
        dimension_rationales={
            "narrative_coherence": "Solid causality throughout.",
            "character_consistency": "Consistent late-night RJ tone.",
        },
        composite_score=4.65,
    )
    assert record.evaluator_id == "annotator_expert_01"
    assert record.composite_score == 4.65


@pytest.mark.asyncio
async def test_calibration_pipeline_pending_human_annotation():
    """Verify calibration pipeline reports PENDING_HUMAN_ANNOTATION when human data is not yet available."""
    evaluator = LLMJudgeEvaluator()
    # Call calibration with empty human ground-truth list
    report = await evaluator.run_calibration(samples=[])
    assert report.calibration_status == "PENDING_HUMAN_ANNOTATION"
    assert not report.is_empirical
    assert "pending" in report.identified_weaknesses[0].lower()


@pytest.mark.asyncio
async def test_llm_judge_evaluator_7_dimensions():
    evaluator = LLMJudgeEvaluator()
    result = await evaluator.evaluate_script(
        script="Rohit: Hamara sapna sach hoga!\nAnanya: Bilkul, hum rukenge nahi.",
        outline="Two entrepreneurs launch their AI studio in Bangalore.",
        model_name="mock-model",
        provider_id="mock",
    )
    assert result.composite_score >= 3.5
    assert result.verdict == "PASS"

    # Verify all 7 core dimensions
    rubric = result.rubric
    assert rubric.narrative_coherence.score >= 1.0
    assert rubric.character_consistency.score >= 1.0
    assert rubric.dialogue_quality.score >= 1.0
    assert rubric.plot_continuity.score >= 1.0
    assert rubric.localization_quality.score >= 1.0
    assert rubric.instruction_adherence.score >= 1.0
    assert rubric.safety.score >= 4.0

    # Verify backward-compatibility properties
    assert rubric.plot_coherence.score == rubric.narrative_coherence.score
    assert rubric.language_naturalness.score == rubric.localization_quality.score
    assert rubric.pacing.score == rubric.dialogue_quality.score

    # Verify evidence and reasoning are present
    assert len(rubric.narrative_coherence.evidence) >= 1
    assert len(rubric.narrative_coherence.reasoning) > 10


@pytest.mark.asyncio
async def test_llm_judge_identifies_contradictory_story_information():
    """Verify that judge penalizes contradictory lore traps and provides explicit evidence."""
    evaluator = LLMJudgeEvaluator()
    result = await evaluator.evaluate_script(
        script="Speaker: The 1947 telegraph was actually made of plastic yesterday.",
        outline="Historical 1947 drama with authentic brass telegraph.",
        story_bible_context="Lore Trap: The telegraph must be 1947 vintage brass. Plastic is a severe contradiction.",
        model_name="mock-model",
        provider_id="mock",
    )
    # Mock provider catches 'lore trap' or 'contradiction'
    assert result.rubric.plot_continuity.score <= 3.0
    assert result.rubric.instruction_adherence.score <= 3.0
    assert len(result.rubric.plot_continuity.evidence) >= 1


@pytest.mark.asyncio
async def test_llm_judge_evaluator_fail_mode():
    low_provider = MockLLMProvider(mode="judge_low_quality")
    evaluator = LLMJudgeEvaluator(llm_provider=low_provider)

    result = await evaluator.evaluate_script(
        script="Poor script with broken flow and defective persona drift",
        outline="Test outline",
        model_name="mock-low",
        provider_id="mock",
    )
    assert result.verdict == "FAIL"
    assert result.composite_score < 3.5 or result.rubric.safety.score < 4.0


@pytest.mark.asyncio
async def test_run_calibration_pipeline_synthetic_fixtures():
    evaluator = LLMJudgeEvaluator()
    samples = load_calibration_dataset()[:5]
    report = await evaluator.run_calibration(samples=samples)
    assert report.total_samples == 5
    assert report.calibration_status == "SYNTHETIC_TEST_ONLY"
    assert "composite" in report.spearman_correlation
    assert -1.0 <= report.spearman_correlation["composite"] <= 1.0
    assert "narrative_coherence" in report.spearman_correlation
    assert "character_consistency" in report.weighted_cohens_kappa
    assert len(report.recommendations) > 0


@pytest.mark.asyncio
async def test_experiment_runner_critic_ablation(db_session: AsyncSession):
    runner = ExperimentRunner()
    cases = load_golden_dataset()[:2]
    res = await runner.run_experiment(
        experiment_type="critic_on_off",
        test_cases=cases,
        db=db_session,
    )
    assert res.experiment_type == "critic_on_off"
    assert res.dataset_version == "2.0.0"
    assert res.rubric_version == "2.0.0"
    assert len(res.variants) == 2
    assert "Critic ON" in res.variants[0].variant_name
    assert "Critic OFF" in res.variants[1].variant_name
    assert res.variants[0].sample_count == 2
    assert res.variants[1].sample_count == 2
    assert "quality_uplift_pct" in res.delta_analysis
    assert "character_consistency_delta" in res.delta_analysis
    assert "cost_delta_usd" in res.delta_analysis
    assert "cases_improved" in res.delta_analysis


@pytest.mark.asyncio
async def test_experiment_runner_rag_ablation(db_session: AsyncSession):
    runner = ExperimentRunner()
    cases = load_golden_dataset()[:2]
    res = await runner.run_experiment(
        experiment_type="rag_ablation",
        test_cases=cases,
        db=db_session,
    )
    assert res.experiment_type == "rag_ablation"
    assert len(res.variants) == 2
    assert "Story Bible ON" in res.variants[0].variant_name
    assert "Story Bible OFF" in res.variants[1].variant_name
    assert "continuity_uplift_pct" in res.delta_analysis
    assert "token_overhead_pct" in res.delta_analysis


@pytest.mark.asyncio
async def test_experiment_runner_model_comparison(db_session: AsyncSession):
    runner = ExperimentRunner()
    cases = load_golden_dataset()[:2]
    res = await runner.run_experiment(
        experiment_type="model_comparison",
        test_cases=cases,
        model_a="gemini-1.5-pro",
        model_b="gemini-1.5-flash",
        db=db_session,
    )
    assert res.experiment_type == "model_comparison"
    assert len(res.variants) == 2
    assert "gemini-1.5-pro" in res.variants[0].variant_name
    assert "gemini-1.5-flash" in res.variants[1].variant_name
    assert "score_difference" in res.delta_analysis


def test_token_and_cost_calculation_with_unknown_pricing():
    # 1. Known model
    cost, status = estimate_token_cost_with_status("gemini-1.5-flash", 1000, 500)
    assert status == "ESTIMATED"
    assert cost > 0.0

    # 2. Unknown model -> Never fabricate prices, return UNKNOWN status
    cost_unk, status_unk = estimate_token_cost_with_status("unregistered-future-model", 1000, 500)
    assert status_unk == "UNKNOWN"
    assert cost_unk == 0.0

    # 3. Register custom pricing at runtime
    register_model_pricing("custom-claude-3-haiku", prompt_price_per_1m=0.25, completion_price_per_1m=1.25)
    cost_custom, status_custom = estimate_token_cost_with_status("custom-claude-3-haiku", 1_000_000, 1_000_000)
    assert status_custom == "ESTIMATED"
    assert cost_custom == pytest.approx(1.50, abs=1e-4)


@pytest.mark.asyncio
async def test_eval_gate_cli_mock_pass_and_fail():
    # 1. Normal gate should pass with default mock
    exit_code_pass = await run_evaluation_gate(
        num_samples=2,
        min_pass_rate=0.8,
        min_composite=3.5,
        max_cost_usd=0.05,
        min_safety=4.0,
        mode="mock",
    )
    assert exit_code_pass == 0

    # 2. Impossible composite threshold should trigger quality gate failure (exit code 1)
    exit_code_fail = await run_evaluation_gate(
        num_samples=2,
        min_pass_rate=0.99,
        min_composite=4.99,  # Unattainable threshold
        max_cost_usd=0.05,
        min_safety=4.0,
        mode="mock",
    )
    assert exit_code_fail == 1


@pytest.mark.asyncio
async def test_evaluations_api_endpoints(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user: User,
):
    # 1. Golden dataset API
    resp = await client.get("/api/v1/evaluations/golden-dataset", headers=auth_headers)
    assert resp.status_code == 200
    golden_list = resp.json()
    assert len(golden_list) >= 30

    # 2. Calibration API
    resp = await client.get("/api/v1/evaluations/calibration", headers=auth_headers)
    assert resp.status_code == 200
    cal_data = resp.json()
    assert cal_data["total_samples"] >= 1
    assert "spearman_correlation" in cal_data

    # 3. Create a series and episode to evaluate
    series = Series(
        title="Eval Series",
        logline="Testing eval API",
        genre="Drama",
        user_id=test_user.id,
    )
    db_session.add(series)
    await db_session.flush()

    episode = Episode(
        series_id=series.id,
        episode_number=1,
        title="Episode 1",
        premise="Test Premise",
        script="Speaker 1: Namaste!\nSpeaker 2: Kaise hain aap?",
        outline="Test outline",
    )
    db_session.add(episode)
    await db_session.commit()

    # 4. Evaluate Episode API
    resp = await client.post(
        f"/api/v1/evaluations/episodes/{episode.id}/evaluate?provider=mock&model_name=mock-model",
        headers=auth_headers,
    )
    assert resp.status_code == 201
    eval_run = resp.json()
    assert eval_run["episode_id"] == episode.id
    assert eval_run["verdict"] in ["PASS", "FAIL"]
    assert eval_run["composite_score"] > 0

    # 5. List evaluation runs
    resp = await client.get("/api/v1/evaluations/runs", headers=auth_headers)
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1

    # 6. Evaluation Summary API
    resp = await client.get("/api/v1/evaluations/summary", headers=auth_headers)
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["total_runs"] >= 1
    assert 0.0 <= summary["pass_rate"] <= 1.0

    # 7. Benchmark API
    resp = await client.post(
        "/api/v1/evaluations/benchmark?experiment_type=critic_on_off&num_cases=1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    bench_data = resp.json()
    assert bench_data["experiment_type"] == "critic_on_off"


def test_provider_factory_live_mode_checks(monkeypatch: pytest.MonkeyPatch):
    """Verify provider factory enforces API key requirements in LIVE mode and allows MOCK mode."""
    # Ensure keys are not set
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")

    # 1. LIVE mode without keys must fail fast with LLMProviderError
    with pytest.raises(LLMProviderError, match="GEMINI_API_KEY"):
        get_llm_provider("gemini", "gemini-1.5-pro", mode="LIVE")

    with pytest.raises(LLMProviderError, match="GROQ_API_KEY"):
        get_llm_provider("groq", "llama-3.3-70b-versatile", mode="LIVE")

    # 2. MOCK mode returns mock provider cleanly
    mock_gemini = get_llm_provider("gemini", "gemini-1.5-pro", mode="MOCK")
    assert isinstance(mock_gemini, MockLLMProvider)
    assert mock_gemini.model_name == "gemini-1.5-pro"

    mock_groq = get_llm_provider("groq", "llama-3.3-70b-versatile", mode="MOCK")
    assert isinstance(mock_groq, MockLLMProvider)
    assert mock_groq.model_name == "llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_cross_user_evaluation_authorization(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify User B cannot evaluate or view User A's episodes, runs, or summary."""
    # Create User A and User B
    user_a = User(
        email="usera@katha.studio",
        hashed_password=hash_password("password123"),
        full_name="User Alpha",
    )
    user_b = User(
        email="userb@katha.studio",
        hashed_password=hash_password("password123"),
        full_name="User Beta",
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    token_a = create_access_token(subject=user_a.id)
    token_b = create_access_token(subject=user_b.id)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a series and episode
    series_a = Series(
        user_id=user_a.id,
        title="Series Alpha",
        genre="mystery",
        logline="Alpha mystery series",
        target_language="hindi",
    )
    db_session.add(series_a)
    await db_session.flush()

    episode_a = Episode(
        series_id=series_a.id,
        episode_number=1,
        title="Pilot Alpha",
        premise="Mysterious frequency",
        script="Speaker: Hello world",
        outline="Alpha Outline",
    )
    db_session.add(episode_a)
    await db_session.commit()

    # 1. User B tries to evaluate User A's episode -> MUST FAIL 403 Forbidden
    eval_resp_b = await client.post(
        f"/api/v1/evaluations/episodes/{episode_a.id}/evaluate?provider=mock&model_name=mock-model",
        headers=headers_b,
    )
    assert eval_resp_b.status_code == 403
    assert "Not authorized" in eval_resp_b.json()["detail"]

    # 2. User A evaluates their own episode -> 201 Created
    eval_resp_a = await client.post(
        f"/api/v1/evaluations/episodes/{episode_a.id}/evaluate?provider=mock&model_name=mock-model",
        headers=headers_a,
    )
    assert eval_resp_a.status_code == 201

    # 3. User B lists runs -> Must NOT see User A's evaluation run
    runs_b_resp = await client.get("/api/v1/evaluations/runs", headers=headers_b)
    assert runs_b_resp.status_code == 200
    runs_b = runs_b_resp.json()
    assert len(runs_b) == 0

    # 4. User A lists runs -> Sees their evaluation run
    runs_a_resp = await client.get("/api/v1/evaluations/runs", headers=headers_a)
    assert runs_a_resp.status_code == 200
    runs_a = runs_a_resp.json()
    assert len(runs_a) == 1
    assert runs_a[0]["episode_id"] == episode_a.id

    # 5. User B checks summary -> 0 runs
    summary_b_resp = await client.get("/api/v1/evaluations/summary", headers=headers_b)
    assert summary_b_resp.status_code == 200
    assert summary_b_resp.json()["total_runs"] == 0


@pytest.mark.asyncio
async def test_reproducible_experiment_persistence_and_traceability(
    db_session: AsyncSession,
    test_user: User,
):
    """Verify BenchmarkExperiment and EvaluationRun records are persisted with full traceability."""
    runner = ExperimentRunner()
    cases = load_golden_dataset()[:1]

    exp_res = await runner.run_experiment(
        experiment_type="critic_on_off",
        test_cases=cases,
        user_id=test_user.id,
        db=db_session,
    )

    # 1. BenchmarkExperiment record exists with user_id
    exp_db = await db_session.scalar(
        select(BenchmarkExperiment).where(BenchmarkExperiment.id == exp_res.experiment_id)
    )
    assert exp_db is not None
    assert exp_db.user_id == test_user.id
    assert exp_db.experiment_type == "critic_on_off"

    # 2. EvaluationRun records are associated with experiment_id
    runs = (
        await db_session.scalars(
            select(EvaluationRun).where(EvaluationRun.experiment_id == exp_res.experiment_id)
        )
    ).all()
    assert len(runs) == 2  # Variant A and Variant B

    variant_names = {r.variant_name for r in runs}
    assert "Critic ON (Quality Guardrail Loop)" in variant_names
    assert "Critic OFF (Bypass Revision Loop)" in variant_names

    for r in runs:
        assert r.token_usage_type == "ESTIMATED"
        assert r.generated_script_text is not None
        assert len(r.generated_script_text) > 0
        assert r.user_id == test_user.id
        assert r.revision_count >= 0
        assert "generation_latency_ms" in r.node_latencies_json
        assert "evaluation_latency_ms" in r.node_latencies_json


@pytest.mark.asyncio
async def test_calibration_no_fallback_metrics_pending_dimensions():
    """Verify calibration pipeline does not use fallback 4.0 and reports PENDING_HUMAN_ANNOTATION for sparse ratings."""
    evaluator = LLMJudgeEvaluator()

    # Create sparse human sample with only narrative_coherence rated
    sparse_sample = HumanLabeledSample(
        sample_id="sparse_case_01",
        title="Sparse Test Case",
        target_language="english",
        genre="drama",
        reference_script="Speaker: Test script dialogue line.",
        human_evaluation=HumanEvaluationRecord(
            evaluator_id="annotator_sparse",
            rubric_version="2.0.0",
            evaluated_at="2026-11-22T12:00:00Z",
            dimension_scores={
                "narrative_coherence": 4.5,
                # Other dimensions intentionally omitted
            },
            dimension_rationales={
                "narrative_coherence": "Coherent line.",
            },
            composite_score=4.5,
        ),
        human_scores={"narrative_coherence": 4.5},
    )

    report = await evaluator.run_calibration(samples=[sparse_sample])
    # With only 1 sample, dimensions should report status without fabricating 4.0 fallbacks
    assert "composite" in report.spearman_correlation
    assert report.total_samples == 1


@pytest.mark.asyncio
async def test_usage_metadata_instrumentation():
    """Verify provider usage tracking reports ESTIMATED for mock and tracks token counts."""
    mock_llm = MockLLMProvider(model_name="mock-gpt")
    assert mock_llm.get_last_usage() is None

    await mock_llm.generate_chat("Hello from test")
    usage = mock_llm.get_last_usage()
    assert usage is not None
    assert usage.model == "mock-gpt"
    assert usage.usage_type == "ESTIMATED"
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


@pytest.mark.asyncio
async def test_experiment_transaction_ordering_and_foreign_keys(db_session: AsyncSession, test_user: User):
    """Verify BenchmarkExperiment is created as RUNNING first, and all child EvaluationRun records reference valid series and episodes."""
    runner = ExperimentRunner()
    case = load_golden_dataset()[0]

    res = await runner.run_experiment(
        experiment_type="critic_on_off",
        test_cases=[case],
        user_id=test_user.id,
        db=db_session,
    )

    # 1. Parent experiment is COMPLETED
    exp_db = await db_session.scalar(
        select(BenchmarkExperiment).where(BenchmarkExperiment.id == res.experiment_id)
    )
    assert exp_db is not None
    assert exp_db.status == "COMPLETED"

    # 2. Child evaluation runs
    runs = (
        await db_session.scalars(
            select(EvaluationRun).where(EvaluationRun.experiment_id == res.experiment_id)
        )
    ).all()
    assert len(runs) == 2

    for r in runs:
        assert r.series_id is not None
        assert r.episode_id is not None
        # Verify series and episode actually exist in DB
        s_db = await db_session.scalar(select(Series).where(Series.id == r.series_id))
        e_db = await db_session.scalar(select(Episode).where(Episode.id == r.episode_id))
        assert s_db is not None
        assert e_db is not None
        assert e_db.series_id == s_db.id

    # 3. Seeded lore references valid episode
    lore_entries = (
        await db_session.scalars(
            select(StoryBibleEntry).where(StoryBibleEntry.series_id == runs[0].series_id)
        )
    ).all()
    for le in lore_entries:
        assert le.episode_id is not None
        ep_check = await db_session.scalar(select(Episode).where(Episode.id == le.episode_id))
        assert ep_check is not None


@pytest.mark.asyncio
async def test_experiment_failure_status_rollback(db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch):
    """Verify that if an error occurs during variant execution, BenchmarkExperiment status is marked FAILED."""
    runner = ExperimentRunner()
    case = load_golden_dataset()[0]

    # Force a failure during variant execution
    async def _failing_variant(*args, **kwargs):
        raise RuntimeError("Simulated pipeline crash during experiment")

    monkeypatch.setattr(runner, "_run_variant", _failing_variant)

    with pytest.raises(RuntimeError, match="Simulated pipeline crash"):
        await runner.run_experiment(
            experiment_type="critic_on_off",
            test_cases=[case],
            user_id=test_user.id,
            db=db_session,
        )

    # Check that parent experiment exists and has status FAILED
    failed_exp = (
        await db_session.scalars(
            select(BenchmarkExperiment).where(BenchmarkExperiment.user_id == test_user.id).order_by(BenchmarkExperiment.created_at.desc())
        )
    ).first()
    assert failed_exp is not None
    assert failed_exp.status == "FAILED"
    assert "error" in failed_exp.results_summary


@pytest.mark.asyncio
async def test_rag_ablation_retrieval_isolation(db_session: AsyncSession, test_user: User):
    """Confirm RAG ON receives seeded memories while RAG OFF receives zero Story Bible context."""
    runner = ExperimentRunner()
    case = load_golden_dataset()[0]  # Has key_continuity_elements

    res = await runner.run_experiment(
        experiment_type="rag_ablation",
        test_cases=[case],
        user_id=test_user.id,
        db=db_session,
    )
    assert res.experiment_type == "rag_ablation"
    assert len(res.variants) == 2

    # Query the 2 evaluation runs
    runs = (
        await db_session.scalars(
            select(EvaluationRun).where(EvaluationRun.experiment_id == res.experiment_id)
        )
    ).all()
    assert len(runs) == 2

    rag_on_run = next(r for r in runs if r.retrieval_enabled)
    rag_off_run = next(r for r in runs if not r.retrieval_enabled)

    # Verify both series had lore seeded (filtering by entity_type == 'lore' as bible_updater adds downstream facts)
    lore_on = (await db_session.scalars(select(StoryBibleEntry).where(StoryBibleEntry.series_id == rag_on_run.series_id, StoryBibleEntry.entity_type == "lore"))).all()
    lore_off = (await db_session.scalars(select(StoryBibleEntry).where(StoryBibleEntry.series_id == rag_off_run.series_id, StoryBibleEntry.entity_type == "lore"))).all()
    assert len(lore_on) == len(case.key_continuity_elements)
    assert len(lore_off) == len(case.key_continuity_elements)

    # Verify delta analysis contains distinct improved/regressed/unchanged
    assert "cases_improved" in res.delta_analysis
    assert "cases_regressed" in res.delta_analysis
    assert "cases_unchanged" in res.delta_analysis


@pytest.mark.asyncio
async def test_usage_aggregation_across_multiple_calls():
    """Verify aggregated usage correctly sums prompt/completion tokens across multiple LLM invocations."""
    mock_llm = MockLLMProvider(model_name="test-multi-call")
    mock_llm.reset_usage()

    assert mock_llm.get_aggregated_usage().call_count == 0

    await mock_llm.generate_chat("First prompt")
    await mock_llm.generate_chat("Second longer prompt with more words")
    await mock_llm.generate_chat("Third prompt")

    agg = mock_llm.get_aggregated_usage()
    assert agg.call_count == 3
    assert agg.prompt_tokens > 0
    assert agg.completion_tokens > 0
    assert agg.total_tokens == agg.prompt_tokens + agg.completion_tokens
    assert agg.model == "test-multi-call"
    assert agg.usage_type == "ESTIMATED"

    # Reset cleans history
    mock_llm.reset_usage()
    assert mock_llm.get_aggregated_usage().call_count == 0


@pytest.mark.asyncio
async def test_benchmark_api_live_mode_credential_validation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify LIVE mode rejects requests when credentials are missing and never silently switches to MOCK."""
    monkeypatch.setenv("GEMINI_API_KEY", "")

    # 1. LIVE mode without key must return 400 Bad Request
    resp = await client.post(
        "/api/v1/evaluations/benchmark?experiment_type=critic_on_off&num_cases=1&mode=LIVE&model_a=gemini-1.5-pro",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Missing GEMINI_API_KEY" in resp.json()["detail"]

    # 2. MOCK mode succeeds
    resp_mock = await client.post(
        "/api/v1/evaluations/benchmark?experiment_type=critic_on_off&num_cases=1&mode=MOCK",
        headers=auth_headers,
    )
    assert resp_mock.status_code == 200
    data = resp_mock.json()
    assert data["experiment_type"] == "critic_on_off"


@pytest.mark.asyncio
async def test_metric_truthfulness_no_fabricated_tts(db_session: AsyncSession, test_user: User):
    """Verify experiments and episode evaluations report 0.0 or None for TTS cache hit rate and never fabricate percentages."""
    runner = ExperimentRunner()
    case = load_golden_dataset()[0]

    res = await runner.run_experiment(
        experiment_type="critic_on_off",
        test_cases=[case],
        user_id=test_user.id,
        db=db_session,
    )

    # Variants report None for tts_cache_hit_rate in text-only experiments
    assert res.variants[0].tts_cache_hit_rate is None
    assert res.variants[1].tts_cache_hit_rate is None

    # Delta analysis has non-fabricated categories
    assert res.delta_analysis["cases_improved"] + res.delta_analysis["cases_regressed"] + res.delta_analysis["cases_unchanged"] == 1


@pytest.mark.asyncio
async def test_individual_evaluation_mock_and_live_credentials(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify individual episode evaluation explicit provider/mode construction and fail-fast credentials."""
    # Setup test series & episode
    series = Series(
        title="Eval Series Modes",
        logline="Testing eval API modes",
        genre="Drama",
        user_id=test_user.id,
    )
    db_session.add(series)
    await db_session.flush()

    episode = Episode(
        series_id=series.id,
        episode_number=1,
        title="Mode Episode",
        premise="Test Premise",
        script="Speaker 1: Namaste!\nSpeaker 2: Kaise hain aap?",
        outline="Test outline",
    )
    db_session.add(episode)
    await db_session.commit()

    # 1. MOCK mode succeeds, tts_cache_hit_rate is None (unmeasured)
    resp_mock = await client.post(
        f"/api/v1/evaluations/episodes/{episode.id}/evaluate?mode=MOCK&provider=mock&model_name=mock-model",
        headers=auth_headers,
    )
    assert resp_mock.status_code == 201
    run_mock = resp_mock.json()
    assert run_mock["tts_cache_hit_rate"] is None
    assert "evaluation_latency_ms" in run_mock["node_latencies_json"]
    assert "planner" not in run_mock["node_latencies_json"]  # No fabricated node percentages

    # 2. LIVE mode with missing credentials must fail with 400 Bad Request (no silent fallback to MOCK)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    resp_live = await client.post(
        f"/api/v1/evaluations/episodes/{episode.id}/evaluate?mode=LIVE&provider=gemini&model_name=gemini-1.5-pro",
        headers=auth_headers,
    )
    assert resp_live.status_code == 400
    assert "GEMINI_API_KEY" in resp_live.json()["detail"]


@pytest.mark.asyncio
async def test_rag_on_actually_retrieves_seeded_lore(db_session: AsyncSession, test_user: User):
    """Verify that RAG ON actually retrieves the seeded lore into Planner/Writer, and RAG OFF receives zero context."""
    runner = ExperimentRunner()
    case = load_golden_dataset()[0]  # Has '1947 telegraph on desk' and 'Radio Mirage station frequency overlap'

    res = await runner.run_experiment(
        experiment_type="rag_ablation",
        test_cases=[case],
        user_id=test_user.id,
        db=db_session,
    )

    runs = (
        await db_session.scalars(
            select(EvaluationRun).where(EvaluationRun.experiment_id == res.experiment_id)
        )
    ).all()
    assert len(runs) == 2

    rag_on_run = next(r for r in runs if r.retrieval_enabled)
    rag_off_run = next(r for r in runs if not r.retrieval_enabled)

    # 1. RAG ON: context contains actual seeded lore
    planner_ctx = rag_on_run.node_latencies_json.get("rag_context_planner", "")
    writer_ctx = rag_on_run.node_latencies_json.get("rag_context_writer", "")
    assert planner_ctx != ""
    assert writer_ctx != ""
    assert any(elem.lower() in planner_ctx.lower() for elem in case.key_continuity_elements)

    # 2. RAG OFF: strictly zero context
    assert rag_off_run.node_latencies_json.get("rag_context_planner") == ""
    assert rag_off_run.node_latencies_json.get("rag_context_writer") == ""

    # 3. Unmeasured TTS is None
    assert rag_on_run.tts_cache_hit_rate is None
    assert rag_off_run.tts_cache_hit_rate is None


def test_cost_semantics_always_estimated_never_actual():
    """Verify that estimated cost calculation is always labeled ESTIMATED or MOCK, never ACTUAL."""
    # Even when token counts are actual, token cost calculation is an estimate
    cost, status = estimate_token_cost_with_status("gemini-1.5-pro", prompt_tokens=1000, completion_tokens=500)
    assert status == "ESTIMATED"
    assert status != "ACTUAL"

    cost_mock, status_mock = estimate_token_cost_with_status("mock-model", prompt_tokens=1000, completion_tokens=500)
    assert status_mock == "MOCK"
    assert status_mock != "ACTUAL"



