import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.eval.calibration_dataset import (
    compute_mae,
    compute_spearman_rho,
    compute_weighted_cohens_kappa,
    load_calibration_dataset,
)
from app.eval.golden_dataset import load_golden_dataset
from app.models.episode import Episode
from app.models.series import Series
from app.models.user import User
from app.providers.mock import MockLLMProvider
from app.services.evaluator import LLMJudgeEvaluator
from app.services.experiments import ExperimentRunner


def test_golden_dataset_structure():
    dataset = load_golden_dataset()
    assert len(dataset) >= 30
    languages = {item.target_language for item in dataset}
    assert "hindi" in languages
    assert "hinglish" in languages
    assert "english" in languages

    for item in dataset:
        assert item.id
        assert item.title
        assert len(item.expected_characters) >= 1
        assert item.target_duration_minutes > 0


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


@pytest.mark.asyncio
async def test_llm_judge_evaluator_pass():
    evaluator = LLMJudgeEvaluator()
    # Use normal mock which gives high scores
    result = await evaluator.evaluate_script(
        script="Rohit: Hamara sapna sach hoga!\nAnanya: Bilkul, hum rukenge nahi.",
        outline="Two entrepreneurs launch their AI studio in Bangalore.",
        model_name="mock-model",
        provider_id="mock",
    )
    assert result.composite_score >= 3.5
    assert result.rubric.safety.score >= 4.0
    assert result.verdict == "PASS"
    assert result.rubric.character_consistency.score >= 1.0
    assert result.rubric.plot_coherence.score >= 1.0
    assert result.rubric.language_naturalness.score >= 1.0
    assert result.rubric.pacing.score >= 1.0


@pytest.mark.asyncio
async def test_llm_judge_evaluator_fail_mode():
    low_provider = MockLLMProvider(mode="judge_low_quality")
    evaluator = LLMJudgeEvaluator(llm_provider=low_provider)

    result = await evaluator.evaluate_script(
        script="Poor script with broken flow",
        outline="Test outline",
        model_name="mock-low",
        provider_id="mock",
    )
    assert result.verdict == "FAIL"
    assert result.composite_score < 3.5 or result.rubric.safety.score < 4.0


@pytest.mark.asyncio
async def test_run_calibration_pipeline():
    evaluator = LLMJudgeEvaluator()
    samples = load_calibration_dataset()[:5]
    report = await evaluator.run_calibration(samples=samples)
    assert report.total_samples == 5
    assert "composite" in report.spearman_correlation
    assert -1.0 <= report.spearman_correlation["composite"] <= 1.0
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
    assert len(res.variants) == 2
    assert "Critic ON" in res.variants[0].variant_name
    assert "Critic OFF" in res.variants[1].variant_name
    assert res.variants[0].sample_count == 2
    assert res.variants[1].sample_count == 2
    assert "quality_uplift_pct" in res.delta_analysis
    assert "cost_delta_usd" in res.delta_analysis


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
    assert res.variants[0].sample_count == 2
    assert res.variants[1].sample_count == 2


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
