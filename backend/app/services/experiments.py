import asyncio
from datetime import datetime, timezone
import logging
import math
import time
import uuid
from typing import Any, Literal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.graph import create_katha_graph
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.telemetry import estimate_token_cost, estimate_token_cost_with_status
from app.eval.golden_dataset import GoldenTestCase, load_golden_dataset
from app.models.episode import Episode
from app.models.evaluation import BenchmarkExperiment, EvaluationRun
from app.models.series import Series
from app.models.story_bible import StoryBibleEntry
from app.models.user import User
from app.providers.base import BaseLLMProvider, ProviderUsageMetadata
from app.providers.factory import get_llm_provider
from app.providers.mock import MockLLMProvider
from app.schemas.evaluation import (
    BenchmarkExperimentResponse,
    EvaluationResult,
    ExperimentVariantMetrics,
)
from app.services.evaluator import LLMJudgeEvaluator, evaluator_service
from app.services.story_bible import story_bible_service

logger = logging.getLogger(__name__)
settings = get_settings()


def format_script_for_eval(final_state: dict[str, Any]) -> str:
    """Format final agent pipeline output into plain text for LLM judge evaluation."""
    cast_script = final_state.get("cast_script")
    localized_script = final_state.get("localized_script")
    raw_script = final_state.get("raw_script")
    outline = final_state.get("outline")

    lines_out: list[str] = []
    title = ""
    if outline:
        title = outline.title
    elif raw_script:
        title = raw_script.title
    elif cast_script:
        title = cast_script.title

    lines_out.append(f"Title: {title}")

    if cast_script and hasattr(cast_script, "scenes"):
        for sc in cast_script.scenes:
            lines_out.append(f"\nScene {sc.scene_number}: {sc.heading}")
            lines_out.append(f"Atmosphere: {sc.atmosphere_soundscape}")
            for line in sc.lines:
                char = getattr(line, "character_name", "UNKNOWN")
                text = getattr(line, "text_localized", getattr(line, "text", ""))
                lines_out.append(f"{char}: {text}")
    elif localized_script and hasattr(localized_script, "scenes"):
        for sc in localized_script.scenes:
            lines_out.append(f"\nScene {sc.scene_number}: {sc.heading}")
            lines_out.append(f"Atmosphere: {sc.atmosphere_soundscape}")
            for line in sc.lines:
                char = getattr(line, "character_name", "UNKNOWN")
                text = getattr(line, "text_localized", getattr(line, "text", ""))
                lines_out.append(f"{char}: {text}")
    elif raw_script and hasattr(raw_script, "scenes"):
        for sc in raw_script.scenes:
            lines_out.append(f"\nScene {sc.scene_number}: {sc.heading}")
            lines_out.append(f"Atmosphere: {sc.atmosphere_soundscape}")
            for line in sc.lines:
                char = getattr(line, "character_name", "UNKNOWN")
                text = getattr(line, "text", "")
                lines_out.append(f"{char}: {text}")
    else:
        lines_out.append("No dialogue generated.")

    return "\n".join(lines_out)


class ExperimentRunner:
    """Orchestrates comparative benchmarking: Critic ON/OFF, RAG Ablation, and Model Comparison."""

    def __init__(self, llm_provider: BaseLLMProvider | None = None) -> None:
        self.llm = llm_provider or MockLLMProvider()

    async def run_experiment(
        self,
        experiment_type: Literal["critic_on_off", "rag_ablation", "model_comparison"],
        test_cases: list[GoldenTestCase] | None = None,
        model_a: str = "gemini-1.5-pro",
        model_b: str = "gemini-1.5-flash",
        provider_a: str | None = None,
        provider_b: str | None = None,
        judge_model: str = "gemini-1.5-pro",
        judge_provider: str | None = None,
        mode: Literal["LIVE", "MOCK"] = "MOCK",
        user_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> BenchmarkExperimentResponse:
        """Execute a controlled multi-variant benchmark experiment across golden test premises."""
        cases = test_cases or load_golden_dataset()[:6]
        experiment_id = str(uuid.uuid4())
        start_time_iso = datetime.now(timezone.utc).isoformat()

        should_close = False
        if db is None:
            session_cm = story_bible_service.get_session()
            db = await session_cm.__aenter__()
            should_close = True

        exp_record: BenchmarkExperiment | None = None

        try:
            # 1. Resolve or create user for valid foreign key constraints
            resolved_user_id = user_id
            if not resolved_user_id:
                user_rec = await db.scalar(select(User.id).limit(1))
                if not user_rec:
                    eval_user = User(
                        id=str(uuid.uuid4()),
                        email="evaluator@katha.studio",
                        hashed_password="mock-password-hash",
                        full_name="Evaluator System",
                    )
                    db.add(eval_user)
                    await db.flush()
                    resolved_user_id = eval_user.id
                else:
                    resolved_user_id = user_rec

            # 2. Derive Experiment Title
            if experiment_type == "critic_on_off":
                title = "Critic Loop Ablation: Feedback Loop vs Raw Draft Generation"
                variant_a_name = "Critic ON (Quality Guardrail Loop)"
                variant_b_name = "Critic OFF (Bypass Revision Loop)"
            elif experiment_type == "rag_ablation":
                title = "Story Bible RAG Ablation: pgvector Hybrid Retrieval vs Zero-Memory Baseline"
                variant_a_name = "Story Bible ON (pgvector Lore Retrieval)"
                variant_b_name = "Story Bible OFF (No Episodic Memory)"
            else:
                title = f"Model Arena Benchmark: {model_a} vs {model_b}"
                variant_a_name = f"Model A ({model_a})"
                variant_b_name = f"Model B ({model_b})"

            # 3. Create and persist parent BenchmarkExperiment with status RUNNING
            # (Ensures all child EvaluationRun records satisfy foreign key constraints)
            exp_record = BenchmarkExperiment(
                id=experiment_id,
                user_id=resolved_user_id,
                title=title,
                experiment_type=experiment_type,
                status="RUNNING",
                results_summary={
                    "dataset_version": "2.0.0",
                    "rubric_version": "2.0.0",
                    "prompt_version": "2.0.0",
                    "execution_mode": mode,
                    "models": [model_a, model_b],
                    "start_time": start_time_iso,
                },
            )
            db.add(exp_record)
            await db.commit()

            # 4. Set up shared judge evaluator: BOTH variants use the EXACT SAME judge to prevent bias
            resolved_judge_provider = judge_provider or ("gemini" if "gemini" in judge_model.lower() else "mock")
            if mode == "LIVE":
                judge_llm = get_llm_provider(resolved_judge_provider, judge_model, mode="LIVE")
                judge_evaluator = LLMJudgeEvaluator(llm_provider=judge_llm)
            else:
                judge_evaluator = LLMJudgeEvaluator(llm_provider=MockLLMProvider(model_name=judge_model, mode="normal"))

            # 5. Resolve generation providers
            res_provider_a = provider_a or ("gemini" if "gemini" in model_a.lower() else "groq" if "groq" in model_a.lower() else "mock")
            res_provider_b = provider_b or ("gemini" if "gemini" in model_b.lower() else "groq" if "groq" in model_b.lower() else "mock")

            # 6. Execute Variants based on experiment type
            if experiment_type == "critic_on_off":
                metrics_a, runs_a = await self._run_variant(
                    variant_name=variant_a_name,
                    experiment_id=experiment_id,
                    cases=cases,
                    critic_enabled=True,
                    retrieval_enabled=True,
                    model_name=model_a,
                    provider=res_provider_a,
                    mode=mode,
                    judge=judge_evaluator,
                    user_id=resolved_user_id,
                    db=db,
                )
                metrics_b, runs_b = await self._run_variant(
                    variant_name=variant_b_name,
                    experiment_id=experiment_id,
                    cases=cases,
                    critic_enabled=False,
                    retrieval_enabled=True,
                    model_name=model_a,
                    provider=res_provider_a,
                    mode=mode,
                    judge=judge_evaluator,
                    user_id=resolved_user_id,
                    db=db,
                )

                improved_count = sum(1 for ra, rb in zip(runs_a, runs_b) if ra.composite_score > rb.composite_score + 0.05)
                regressed_count = sum(1 for ra, rb in zip(runs_a, runs_b) if ra.composite_score < rb.composite_score - 0.05)
                unchanged_count = len(cases) - (improved_count + regressed_count)

                if improved_count > regressed_count:
                    conclusion = (
                        f"Critic revision loop demonstrated empirical quality gains in {improved_count}/{len(cases)} cases "
                        f"({regressed_count} regressions, {unchanged_count} unchanged)."
                    )
                elif regressed_count > improved_count:
                    conclusion = (
                        f"Critic revision loop showed regressions in {regressed_count}/{len(cases)} cases versus "
                        f"{improved_count} improvements ({unchanged_count} unchanged)."
                    )
                elif len(cases) == 0:
                    conclusion = "Inconclusive: No benchmark cases were evaluated."
                else:
                    conclusion = (
                        f"Inconclusive: Balanced outcomes ({improved_count} improved, {regressed_count} regressed, "
                        f"{unchanged_count} unchanged) across {len(cases)} cases; insufficient evidence of significant difference."
                    )

                delta_analysis = {
                    "quality_uplift_pct": round(
                        ((metrics_a.avg_composite_score - metrics_b.avg_composite_score) / max(0.1, metrics_b.avg_composite_score)) * 100.0,
                        2,
                    ),
                    "character_consistency_delta": round(
                        metrics_a.avg_character_consistency - metrics_b.avg_character_consistency, 2
                    ),
                    "plot_continuity_delta": round(
                        metrics_a.avg_plot_continuity - metrics_b.avg_plot_continuity, 2
                    ),
                    "narrative_coherence_delta": round(
                        metrics_a.avg_narrative_coherence - metrics_b.avg_narrative_coherence, 2
                    ),
                    "dialogue_quality_delta": round(
                        metrics_a.avg_dialogue_quality - metrics_b.avg_dialogue_quality, 2
                    ),
                    "cases_improved": improved_count,
                    "cases_regressed": regressed_count,
                    "cases_unchanged": unchanged_count,
                    "latency_overhead_pct": round(
                        ((metrics_a.avg_latency_ms - metrics_b.avg_latency_ms) / max(1.0, metrics_b.avg_latency_ms)) * 100.0,
                        2,
                    ),
                    "cost_delta_usd": round(metrics_a.avg_cost_usd - metrics_b.avg_cost_usd, 6),
                    "conclusion": conclusion,
                }

            elif experiment_type == "rag_ablation":
                metrics_a, runs_a = await self._run_variant(
                    variant_name=variant_a_name,
                    experiment_id=experiment_id,
                    cases=cases,
                    critic_enabled=True,
                    retrieval_enabled=True,
                    model_name=model_a,
                    provider=res_provider_a,
                    mode=mode,
                    judge=judge_evaluator,
                    user_id=resolved_user_id,
                    db=db,
                )
                metrics_b, runs_b = await self._run_variant(
                    variant_name=variant_b_name,
                    experiment_id=experiment_id,
                    cases=cases,
                    critic_enabled=True,
                    retrieval_enabled=False,
                    model_name=model_a,
                    provider=res_provider_a,
                    mode=mode,
                    judge=judge_evaluator,
                    user_id=resolved_user_id,
                    db=db,
                )

                improved_count = sum(1 for ra, rb in zip(runs_a, runs_b) if ra.composite_score > rb.composite_score + 0.05)
                regressed_count = sum(1 for ra, rb in zip(runs_a, runs_b) if ra.composite_score < rb.composite_score - 0.05)
                unchanged_count = len(cases) - (improved_count + regressed_count)

                if improved_count > regressed_count:
                    conclusion = (
                        f"Story Bible retrieval improved continuity and consistency in {improved_count}/{len(cases)} cases "
                        f"({regressed_count} regressed, {unchanged_count} unchanged)."
                    )
                elif regressed_count > improved_count:
                    conclusion = (
                        f"Story Bible retrieval showed lower scores in {regressed_count}/{len(cases)} cases versus "
                        f"{improved_count} improvements ({unchanged_count} unchanged)."
                    )
                else:
                    conclusion = (
                        f"Inconclusive: Story Bible retrieval yielded neutral impact across {len(cases)} benchmark samples "
                        f"({improved_count} improved, {regressed_count} regressed, {unchanged_count} unchanged)."
                    )

                token_overhead_pct = round(
                    ((metrics_a.avg_tokens - metrics_b.avg_tokens) / max(1, metrics_b.avg_tokens)) * 100.0,
                    2,
                )

                delta_analysis = {
                    "continuity_uplift_pct": round(
                        ((metrics_a.avg_plot_continuity - metrics_b.avg_plot_continuity) / max(0.1, metrics_b.avg_plot_continuity)) * 100.0,
                        2,
                    ),
                    "character_consistency_delta": round(
                        metrics_a.avg_character_consistency - metrics_b.avg_character_consistency, 2
                    ),
                    "plot_continuity_delta": round(
                        metrics_a.avg_plot_continuity - metrics_b.avg_plot_continuity, 2
                    ),
                    "instruction_adherence_delta": round(
                        metrics_a.avg_instruction_adherence - metrics_b.avg_instruction_adherence, 2
                    ),
                    "quality_uplift_pct": round(
                        ((metrics_a.avg_composite_score - metrics_b.avg_composite_score) / max(0.1, metrics_b.avg_composite_score)) * 100.0,
                        2,
                    ),
                    "cases_improved": improved_count,
                    "cases_regressed": regressed_count,
                    "cases_unchanged": unchanged_count,
                    "token_overhead_pct": token_overhead_pct,
                    "cost_delta_usd": round(metrics_a.avg_cost_usd - metrics_b.avg_cost_usd, 6),
                    "retrieval_latency_overhead_ms": round(
                        metrics_a.avg_latency_ms - metrics_b.avg_latency_ms, 2
                    ),
                    "conclusion": conclusion,
                }

            else:  # model_comparison
                metrics_a, runs_a = await self._run_variant(
                    variant_name=variant_a_name,
                    experiment_id=experiment_id,
                    cases=cases,
                    critic_enabled=True,
                    retrieval_enabled=True,
                    model_name=model_a,
                    provider=res_provider_a,
                    mode=mode,
                    judge=judge_evaluator,
                    user_id=resolved_user_id,
                    db=db,
                )
                metrics_b, runs_b = await self._run_variant(
                    variant_name=variant_b_name,
                    experiment_id=experiment_id,
                    cases=cases,
                    critic_enabled=True,
                    retrieval_enabled=True,
                    model_name=model_b,
                    provider=res_provider_b,
                    mode=mode,
                    judge=judge_evaluator,
                    user_id=resolved_user_id,
                    db=db,
                )

                if metrics_a.avg_composite_score > metrics_b.avg_composite_score + 0.1:
                    recommendation = f"{model_a} demonstrated higher average composite quality ({metrics_a.avg_composite_score} vs {metrics_b.avg_composite_score})."
                elif metrics_b.avg_composite_score > metrics_a.avg_composite_score + 0.1:
                    recommendation = f"{model_b} demonstrated higher average composite quality ({metrics_b.avg_composite_score} vs {metrics_a.avg_composite_score})."
                else:
                    recommendation = f"Both models achieved comparable overall scores ({metrics_a.avg_composite_score} vs {metrics_b.avg_composite_score}); evaluate latency and cost trade-offs."

                delta_analysis = {
                    "score_difference": round(metrics_a.avg_composite_score - metrics_b.avg_composite_score, 2),
                    "speedup_factor": round(metrics_a.avg_latency_ms / max(1.0, metrics_b.avg_latency_ms), 2),
                    "cost_status_a": metrics_a.cost_status,
                    "cost_status_b": metrics_b.cost_status,
                    "cost_ratio": round(metrics_a.avg_cost_usd / max(0.00001, metrics_b.avg_cost_usd), 2) if metrics_a.avg_cost_usd > 0 and metrics_b.avg_cost_usd > 0 else 1.0,
                    "cost_savings_pct": round(
                        ((metrics_a.avg_cost_usd - metrics_b.avg_cost_usd) / max(0.00001, metrics_a.avg_cost_usd)) * 100.0,
                        2,
                    ) if metrics_a.avg_cost_usd > 0 else 0.0,
                    "failure_rate_delta": round(metrics_a.failure_rate - metrics_b.failure_rate, 2),
                    "validation_failures_total": (metrics_a.validation_failures or 0) + (metrics_b.validation_failures or 0),
                    "recommendation": recommendation,
                }

            completed_time_iso = datetime.now(timezone.utc).isoformat()

            # 7. Update parent experiment to COMPLETED
            exp_record.status = "COMPLETED"
            exp_record.results_summary = {
                "dataset_version": "2.0.0",
                "rubric_version": "2.0.0",
                "prompt_version": "2.0.0",
                "execution_mode": mode,
                "models": [model_a, model_b],
                "start_time": start_time_iso,
                "completed_time": completed_time_iso,
                "variants": [metrics_a.model_dump(), metrics_b.model_dump()],
                "delta_analysis": delta_analysis,
                "total_samples": len(cases),
            }
            await db.commit()

            return BenchmarkExperimentResponse(
                experiment_id=experiment_id,
                experiment_type=experiment_type,
                title=title,
                dataset_version="2.0.0",
                rubric_version="2.0.0",
                prompt_version="2.0.0",
                variants=[metrics_a, metrics_b],
                delta_analysis=delta_analysis,
                created_at=completed_time_iso,
            )

        except Exception as exc:
            logger.error(f"Experiment execution failed: {exc}", exc_info=True)
            if exp_record is not None:
                try:
                    exp_record.status = "FAILED"
                    exp_record.results_summary = {
                        "error": str(exc),
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await db.commit()
                except Exception as commit_err:
                    logger.error(f"Failed to update experiment status to FAILED: {commit_err}")
                    await db.rollback()
            else:
                await db.rollback()
            raise
        finally:
            if should_close:
                await db.close()

    async def _run_variant(
        self,
        variant_name: str,
        experiment_id: str,
        cases: list[GoldenTestCase],
        critic_enabled: bool,
        retrieval_enabled: bool,
        model_name: str,
        provider: str,
        mode: Literal["LIVE", "MOCK"],
        judge: LLMJudgeEvaluator,
        user_id: str,
        db: AsyncSession,
    ) -> tuple[ExperimentVariantMetrics, list[EvaluationRun]]:
        """Run a set of test cases under specific experimental conditions and compute aggregate metrics."""
        scores: list[float] = []
        narr_scores: list[float] = []
        char_scores: list[float] = []
        dial_scores: list[float] = []
        plot_scores: list[float] = []
        loc_scores: list[float] = []
        inst_scores: list[float] = []
        safe_scores: list[float] = []
        latencies: list[float] = []
        tokens_list: list[int] = []
        costs: list[float] = []
        pass_count = 0
        validation_failures_total = 0
        revision_count_total = 0
        cost_status_overall = "MOCK" if mode == "MOCK" else "ESTIMATED"
        runs: list[EvaluationRun] = []

        # Instantiate the generation LLM
        gen_llm = get_llm_provider(provider_name=provider, model_name=model_name, mode=mode)
        graph = create_katha_graph(llm=gen_llm)

        for case in cases:
            # 1. Setup isolated series AND actual episode records in PostgreSQL
            series_id = f"exp-{uuid.uuid4().hex[:12]}"
            episode_id = f"ep-{uuid.uuid4().hex[:12]}"

            series_rec = Series(
                id=series_id,
                user_id=user_id,
                title=f"{case.title} ({variant_name[:20]})",
                genre=case.genre,
                logline=case.premise,
                target_language=case.target_language,
                status="active",
            )
            db.add(series_rec)

            episode_rec = Episode(
                id=episode_id,
                series_id=series_id,
                episode_number=1,
                title=case.title,
                premise=case.premise,
                target_language=case.target_language,
                duration_minutes_target=case.target_duration_minutes,
                status="DRAFT",
            )
            db.add(episode_rec)
            await db.flush()

            # 2. Seed lore referencing valid series_id AND episode_id
            if case.key_continuity_elements:
                for idx, elem in enumerate(case.key_continuity_elements, start=1):
                    emb = await story_bible_service.embedding_provider.embed_text(elem)
                    entry = StoryBibleEntry(
                        series_id=series_id,
                        episode_id=episode_id,
                        entity_type="lore",
                        entity_name=f"Lore Element {idx}",
                        content=elem,
                        embedding=emb,
                        metadata_json={"importance": "high"},
                    )
                    db.add(entry)

            # Commit the seeded lore before executing LangGraph
            await db.commit()

            # 3. Run actual LangGraph pipeline generation
            initial_state = {
                "series_id": series_id,
                "episode_id": episode_id,
                "episode_number": 1,
                "premise": case.premise,
                "target_language": case.target_language,
                "target_duration_minutes": case.target_duration_minutes,
                "genre": case.genre,
                "characters_hint": case.expected_characters,
                "simulation_flags": {
                    "disable_critic": not critic_enabled,
                    "retrieval_enabled": retrieval_enabled,
                },
            }

            gen_llm.reset_usage()
            gen_start_ts = time.perf_counter()
            final_state = await graph.ainvoke(initial_state)
            gen_latency_ms = (time.perf_counter() - gen_start_ts) * 1000.0

            # 4. Verify RAG Isolation & Retrieval Context
            planner_rag_ctx = final_state.get("story_bible_context_planner") or ""
            writer_rag_ctx = final_state.get("story_bible_context_writer") or ""
            if not retrieval_enabled:
                if planner_rag_ctx:
                    raise AssertionError(f"RAG OFF violation: Planner received unexpected lore context: {planner_rag_ctx[:100]}")
                if writer_rag_ctx:
                    raise AssertionError(f"RAG OFF violation: Writer received unexpected lore context: {writer_rag_ctx[:100]}")
            else:
                if case.key_continuity_elements:
                    if not planner_rag_ctx:
                        raise AssertionError(f"RAG ON violation: Planner received no lore context for case '{case.id}'.")
                    if not writer_rag_ctx:
                        raise AssertionError(f"RAG ON violation: Writer received no lore context for case '{case.id}'.")
                    retrieved_match = any(
                        elem.lower() in planner_rag_ctx.lower() or elem.lower() in writer_rag_ctx.lower()
                        for elem in case.key_continuity_elements
                    )
                    if not retrieved_match:
                        raise AssertionError(
                            f"RAG ON violation: Seeded lore elements {case.key_continuity_elements} "
                            f"not found in retrieved context for case '{case.id}'."
                        )

            # 5. Format actual generated script and extract actual revisions & validation errors
            generated_script_text = format_script_for_eval(final_state)
            revisions = final_state.get("revision_count", 0)
            errors_in_state = final_state.get("errors", [])
            validation_failures_total += len(errors_in_state)

            # 6. Aggregate generation usage across all graph node calls
            gen_usage = gen_llm.get_aggregated_usage()
            gen_prompt_tokens = gen_usage.prompt_tokens
            gen_completion_tokens = gen_usage.completion_tokens
            gen_usage_type = gen_usage.usage_type
            gen_cost_usd, gen_cost_status = estimate_token_cost_with_status(model_name, gen_prompt_tokens, gen_completion_tokens)

            # 7. Evaluate the generated script using the shared judge
            if hasattr(judge.llm, "reset_usage"):
                judge.llm.reset_usage()
            eval_start_ts = time.perf_counter()
            eval_res: EvaluationResult = await judge.evaluate_script(
                script=generated_script_text,
                outline=f"Genre: {case.genre}\nDuration: {case.target_duration_minutes}m\nPremise: {case.premise}",
                story_bible_context=f"Known Lore: {', '.join(case.key_continuity_elements)}" if retrieval_enabled else "",
                model_name=model_name,
                provider_id=provider,
            )
            eval_latency_ms = (time.perf_counter() - eval_start_ts) * 1000.0
            total_latency_ms = gen_latency_ms + eval_latency_ms

            # 8. Aggregate judge usage
            judge_usage = judge.llm.get_aggregated_usage() if hasattr(judge.llm, "get_aggregated_usage") else ProviderUsageMetadata()
            judge_cost_usd, judge_cost_status = estimate_token_cost_with_status(
                getattr(judge, "model_name", "gemini-1.5-pro"),
                judge_usage.prompt_tokens,
                judge_usage.completion_tokens,
            )

            # Overall usage classification
            if gen_usage_type == "ACTUAL" and judge_usage.usage_type == "ACTUAL":
                overall_token_usage_type = "ACTUAL"
            elif gen_usage_type == "MOCK" or judge_usage.usage_type == "MOCK":
                overall_token_usage_type = "MOCK"
            else:
                overall_token_usage_type = "ESTIMATED"

            total_prompt_tokens = gen_prompt_tokens + judge_usage.prompt_tokens
            total_completion_tokens = gen_completion_tokens + judge_usage.completion_tokens
            total_cost_usd = round(gen_cost_usd + judge_cost_usd, 6)

            # 9. Extract raw, unmodified scores from judge
            char_score = eval_res.rubric.character_consistency.score
            plot_score = eval_res.rubric.plot_continuity.score
            inst_score = eval_res.rubric.instruction_adherence.score
            narr_score = eval_res.rubric.narrative_coherence.score
            dial_score = eval_res.rubric.dialogue_quality.score
            loc_score = eval_res.rubric.localization_quality.score
            safe_score = eval_res.rubric.safety.score
            composite_score = eval_res.composite_score

            scores.append(composite_score)
            narr_scores.append(narr_score)
            char_scores.append(char_score)
            dial_scores.append(dial_score)
            plot_scores.append(plot_score)
            loc_scores.append(loc_score)
            inst_scores.append(inst_score)
            safe_scores.append(safe_score)
            latencies.append(total_latency_ms)
            tokens_list.append(total_prompt_tokens + total_completion_tokens)
            costs.append(total_cost_usd)
            revision_count_total += revisions

            # Pass rate determined by eval_res.passed (which includes safety threshold)
            if eval_res.passed:
                pass_count += 1

            # 10. Persist individual run with valid foreign keys and reproducibility metadata
            run_record = EvaluationRun(
                experiment_id=experiment_id,
                variant_name=variant_name,
                series_id=series_id,
                episode_id=episode_id,
                token_usage_type=overall_token_usage_type,
                generated_script_text=generated_script_text,
                user_id=user_id,
                test_case_id=case.id,
                model_name=model_name,
                provider=provider,
                critic_enabled=critic_enabled,
                retrieval_enabled=retrieval_enabled,
                latency_ms=round(total_latency_ms, 2),
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                estimated_cost_usd=total_cost_usd,
                revision_count=revisions,
                tts_cache_hit_rate=None,  # Unmeasured in text generation experiments
                composite_score=composite_score,
                character_consistency=char_score,
                plot_coherence=narr_score,
                language_naturalness=loc_score,
                pacing=dial_score,
                safety=safe_score,
                passed=eval_res.passed,
                verdict=eval_res.verdict,
                scores_json=eval_res.rubric.model_dump(),
                node_latencies_json={
                    "generation_latency_ms": round(gen_latency_ms, 1),
                    "evaluation_latency_ms": round(eval_latency_ms, 1),
                    "rag_context_planner": planner_rag_ctx,
                    "rag_context_writer": writer_rag_ctx,
                    "usage_breakdown": {
                        "generation": {
                            "model": gen_usage.model or model_name,
                            "provider": gen_usage.provider or provider,
                            "prompt_tokens": gen_prompt_tokens,
                            "completion_tokens": gen_completion_tokens,
                            "total_tokens": gen_prompt_tokens + gen_completion_tokens,
                            "latency_ms": round(gen_latency_ms, 1),
                            "usage_type": gen_usage_type,
                            "estimated_cost_usd": gen_cost_usd,
                            "cost_status": gen_cost_status,
                            "call_count": gen_usage.call_count,
                        },
                        "judge": {
                            "model": judge_usage.model or getattr(judge, "model_name", "gemini-1.5-pro"),
                            "provider": judge_usage.provider or getattr(judge, "provider_id", "gemini"),
                            "prompt_tokens": judge_usage.prompt_tokens,
                            "completion_tokens": judge_usage.completion_tokens,
                            "total_tokens": judge_usage.prompt_tokens + judge_usage.completion_tokens,
                            "latency_ms": round(eval_latency_ms, 1),
                            "usage_type": judge_usage.usage_type,
                            "estimated_cost_usd": judge_cost_usd,
                            "cost_status": judge_cost_status,
                            "call_count": judge_usage.call_count,
                        },
                    },
                },
                feedback=eval_res.rubric.overall_critique,
            )
            db.add(run_record)
            runs.append(run_record)

        await db.commit()

        # Compute P50 and P95 latency
        sorted_latencies = sorted(latencies)
        p50_idx = int(len(sorted_latencies) * 0.5)
        p95_idx = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
        p50_lat = sorted_latencies[p50_idx] if sorted_latencies else 0.0
        p95_lat = sorted_latencies[p95_idx] if sorted_latencies else 0.0

        n = max(1, len(cases))
        metrics = ExperimentVariantMetrics(
            variant_name=variant_name,
            sample_count=len(cases),
            avg_composite_score=round(sum(scores) / n, 2),
            avg_narrative_coherence=round(sum(narr_scores) / n, 2),
            avg_character_consistency=round(sum(char_scores) / n, 2),
            avg_dialogue_quality=round(sum(dial_scores) / n, 2),
            avg_plot_continuity=round(sum(plot_scores) / n, 2),
            avg_localization_quality=round(sum(loc_scores) / n, 2),
            avg_instruction_adherence=round(sum(inst_scores) / n, 2),
            avg_safety=round(sum(safe_scores) / n, 2),
            avg_plot_coherence=round(sum(narr_scores) / n, 2),
            avg_language_naturalness=round(sum(loc_scores) / n, 2),
            avg_pacing=round(sum(dial_scores) / n, 2),
            avg_latency_ms=round(sum(latencies) / n, 2),
            p50_latency_ms=round(p50_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
            avg_tokens=int(sum(tokens_list) / n),
            avg_cost_usd=round(sum(costs) / n, 6),
            cost_status=cost_status_overall,
            pass_rate=round(pass_count / n, 2),
            failure_rate=round((n - pass_count) / n, 2),
            revision_rate=round(revision_count_total / n, 2),
            validation_failures=validation_failures_total,
            tts_cache_hit_rate=None,  # Not measured in text-generation experiments
        )
        return metrics, runs


experiment_runner = ExperimentRunner()
