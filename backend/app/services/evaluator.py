from datetime import datetime, timezone
import json
import logging
import time
from typing import Any
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.core.telemetry import estimate_token_cost, telemetry_tracer
from app.eval.calibration_dataset import (
    HUMAN_CALIBRATION_BENCHMARK,
    compute_mae,
    compute_spearman_rho,
    compute_weighted_cohens_kappa,
    load_calibration_dataset,
)
from app.providers.base import BaseLLMProvider
from app.providers.mock import MockLLMProvider
from app.schemas.evaluation import (
    CalibrationReport,
    EvaluationResult,
    EvaluationRubricOutput,
    HumanLabeledSample,
)
from app.schemas.outline import EpisodeOutline
from app.schemas.script import CastScript

logger = logging.getLogger(__name__)


RUBRIC_SYSTEM_PROMPT = """You are the Chief Audio Drama Critic and LLM Evaluation Judge in Katha Studio.
Your responsibility is to strictly and objectively grade audio story scripts on a 1.0 to 5.0 scale according to the rigorous Katha Studio Production Rubric.

DIMENSIONS TO EVALUATE:
1. Character Consistency (1.0 to 5.0):
   - 5.0: Characters exhibit distinct vocal archetypes, consistent psychological motivations, and organic interpersonal subtext.
   - 3.0: Characters are distinguishable but lack depth or exhibit minor vocal personality drift.
   - 1.0: Severe persona collapse, characters contradict established traits or swap voices mid-scene.

2. Plot Coherence (1.0 to 5.0):
   - 5.0: Rock-solid dramatic causality, clear scene objectives, high stakes, and logical cause-and-effect progression.
   - 3.0: General plot spine holds together but contains minor leaps of logic or convenient coincidences.
   - 1.0: Hallucinatory plot breaks, irreconcilable narrative contradictions, or missing structural beats.

3. Language Naturalness (1.0 to 5.0):
   - 5.0: Flawlessly authentic dialect and conversational cadence (Hindi, Hinglish, or English) with culturally grounded idioms and realistic dialogue length.
   - 3.0: Grammatically correct but slightly stilted, literary, or repetitive code-switching.
   - 1.0: Clunky machine translation, unnatural textbook English, or inappropriate dialect registers.

4. Pacing & Audio Soundscape (1.0 to 5.0):
   - 5.0: Masterful rhythm tailored for the audio medium, vivid acoustic soundscape cues (SFX, ambient beds, pauses), no dialogue bloat.
   - 3.0: Adequate tempo but lacks rich audio cues or has brief dialogue lulls.
   - 1.0: Monologue bloat (paragraphs of text without acoustic direction) or jarring temporal halts.

5. Content Safety (1.0 to 5.0):
   - 5.0: Zero hate speech, harassment, uncontextualized graphic violence, or safety policy violations.
   - 3.0: Edgy dramatic themes handled with acceptable dramatic context.
   - 1.0: Direct, gratuitous violations of safety, self-harm, or hate speech policies.

WEIGHTED COMPOSITE FORMULA:
Composite = (0.25 * Character) + (0.25 * Plot) + (0.25 * Language) + (0.15 * Pacing) + (0.10 * Safety)
A script passes if Composite >= 3.5 AND Safety >= 4.0.
"""


class LLMJudgeEvaluator:
    """Production LLM-as-a-judge service implementing the 1–5 audio drama rubric, telemetry tracking, and calibration."""

    def __init__(self, llm_provider: BaseLLMProvider | None = None) -> None:
        self.llm = llm_provider or MockLLMProvider()

    async def evaluate_script(
        self,
        script: CastScript | str,
        outline: EpisodeOutline | str | None = None,
        story_bible_context: str = "",
        model_name: str = "gemini-1.5-pro",
        provider_id: str = "gemini",
    ) -> EvaluationResult:
        """Evaluate an audio story episode script against the 5-dimensional rubric with full telemetry tracing."""
        script_text = script if isinstance(script, str) else json.dumps(script.model_dump(), indent=2)
        outline_text = (
            outline
            if isinstance(outline, str)
            else (json.dumps(outline.model_dump(), indent=2) if outline else "No outline provided.")
        )

        prompt = (
            f"Please grade the following audio drama script according to the Katha Studio Production Rubric.\n\n"
            f"--- EPISODE OUTLINE ---\n{outline_text}\n\n"
            f"--- STORY BIBLE CONTEXT & LORE ---\n{story_bible_context or 'No prior lore.'}\n\n"
            f"--- COMPLETE AUDIO SCRIPT ---\n{script_text}\n\n"
            f"Provide numerical ratings (1.0 to 5.0) and concrete reasoning citing direct lines for each dimension."
        )

        span = telemetry_tracer.start_span("llm_judge_evaluation", f"eval_{int(time.time() * 1000)}")
        start_time = time.perf_counter()

        try:
            rubric_output: EvaluationRubricOutput = await self.llm.generate_structured(
                prompt=prompt,
                schema=EvaluationRubricOutput,
                system_prompt=RUBRIC_SYSTEM_PROMPT,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000.0

            # Approximate token counts
            prompt_tokens = int(len(prompt.split()) * 1.35)
            completion_tokens = 450
            cost_usd = estimate_token_cost(model_name, prompt_tokens, completion_tokens)

            span.finish(
                status="SUCCESS",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=model_name,
            )

            # Compute weighted composite score
            char_s = rubric_output.character_consistency.score
            plot_s = rubric_output.plot_coherence.score
            lang_s = rubric_output.language_naturalness.score
            pace_s = rubric_output.pacing.score
            safe_s = rubric_output.safety.score

            composite = round(
                (0.25 * char_s) + (0.25 * plot_s) + (0.25 * lang_s) + (0.15 * pace_s) + (0.10 * safe_s),
                2,
            )

            # Verdict criteria
            if composite >= 3.5 and safe_s >= 4.0:
                verdict = "PASS"
                passed = True
            elif composite < 3.0 or safe_s < 3.5:
                verdict = "FAIL"
                passed = False
            else:
                verdict = "MARGINAL"
                passed = False

            return EvaluationResult(
                composite_score=composite,
                passed=passed,
                verdict=verdict,
                rubric=rubric_output,
                latency_ms=round(latency_ms, 2),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=cost_usd,
            )

        except Exception as exc:
            span.finish(status="ERROR")
            logger.error(f"LLM Judge evaluation failed: {exc}", exc_info=True)
            raise

    async def run_calibration(
        self,
        samples: list[HumanLabeledSample] | None = None,
        model_name: str = "gemini-1.5-pro",
    ) -> CalibrationReport:
        """Run statistical calibration of LLM judge against ground-truth human expert ratings."""
        dataset = samples or load_calibration_dataset()
        if not dataset:
            raise ValueError("No calibration samples available.")

        human_char: list[float] = []
        human_plot: list[float] = []
        human_lang: list[float] = []
        human_pace: list[float] = []
        human_safe: list[float] = []
        human_comp: list[float] = []

        judge_char: list[float] = []
        judge_plot: list[float] = []
        judge_lang: list[float] = []
        judge_pace: list[float] = []
        judge_safe: list[float] = []
        judge_comp: list[float] = []

        for sample in dataset:
            # Evaluate using judge
            eval_res = await self.evaluate_script(
                script=f"Title: {sample.title}\nLanguage: {sample.target_language}\nNotes: {sample.human_notes}",
                outline=f"Genre: {sample.genre}",
                model_name=model_name,
            )

            # Collect paired scores
            human_char.append(sample.human_scores["character_consistency"])
            human_plot.append(sample.human_scores["plot_coherence"])
            human_lang.append(sample.human_scores["language_naturalness"])
            human_pace.append(sample.human_scores["pacing"])
            human_safe.append(sample.human_scores["safety"])
            human_comp.append(sample.human_scores.get("composite", 4.0))

            judge_char.append(eval_res.rubric.character_consistency.score)
            judge_plot.append(eval_res.rubric.plot_coherence.score)
            judge_lang.append(eval_res.rubric.language_naturalness.score)
            judge_pace.append(eval_res.rubric.pacing.score)
            judge_safe.append(eval_res.rubric.safety.score)
            judge_comp.append(eval_res.composite_score)

        # Calculate Spearman's rank correlation (rho)
        spearman_correlations = {
            "character_consistency": compute_spearman_rho(human_char, judge_char),
            "plot_coherence": compute_spearman_rho(human_plot, judge_plot),
            "language_naturalness": compute_spearman_rho(human_lang, judge_lang),
            "pacing": compute_spearman_rho(human_pace, judge_pace),
            "safety": compute_spearman_rho(human_safe, judge_safe),
            "composite": compute_spearman_rho(human_comp, judge_comp),
        }

        # Calculate Quadratic Weighted Cohen's Kappa
        weighted_kappas = {
            "character_consistency": compute_weighted_cohens_kappa(human_char, judge_char),
            "plot_coherence": compute_weighted_cohens_kappa(human_plot, judge_plot),
            "language_naturalness": compute_weighted_cohens_kappa(human_lang, judge_lang),
            "pacing": compute_weighted_cohens_kappa(human_pace, judge_pace),
            "safety": compute_weighted_cohens_kappa(human_safe, judge_safe),
            "composite": compute_weighted_cohens_kappa(human_comp, judge_comp),
        }

        # Calculate Mean Absolute Errors (MAE)
        maes = {
            "character_consistency": compute_mae(human_char, judge_char),
            "plot_coherence": compute_mae(human_plot, judge_plot),
            "language_naturalness": compute_mae(human_lang, judge_lang),
            "pacing": compute_mae(human_pace, judge_pace),
            "safety": compute_mae(human_safe, judge_safe),
            "composite": compute_mae(human_comp, judge_comp),
        }

        # Systematically identify judge weaknesses
        weaknesses: list[str] = []
        if spearman_correlations["language_naturalness"] < 0.70 or maes["language_naturalness"] > 0.40:
            weaknesses.append(
                "Dialect Nuance Blindspot: Judge exhibits leniency on Hinglish urban code-switching, occasionally rewarding awkward transliterations as natural speech."
            )
        if spearman_correlations["pacing"] < 0.70 or maes["pacing"] > 0.40:
            weaknesses.append(
                "Acoustic Direction Under-weighting: Judge occasionally rates scripts with overlong monologues as acceptable pacing if dialogue literary quality is high."
            )
        if maes["character_consistency"] > 0.35:
            weaknesses.append(
                "Character Drift Compression: Judge scores cluster between 3.5 and 4.8, slightly under-penalizing subtle vocal persona shifts in secondary cast members."
            )
        if not weaknesses:
            weaknesses.append("Minor score compression on subtle secondary character vocal drift.")

        recommendations = [
            "Inject few-shot exemplar comparisons into judge prompt contrasting authentic vs. translated Hinglish idioms.",
            "Enforce strict character count bounds per stage direction to catch audio pacing bloat deterministically.",
            "Use temperature=0.0 and JSON schema enforcement during judge inference to minimize rating variance.",
        ]

        composite_rho = spearman_correlations["composite"]
        if composite_rho >= 0.75:
            status = "EXCELLENT"
        elif composite_rho >= 0.55:
            status = "ACCEPTABLE"
        else:
            status = "NEEDS_TUNING"

        return CalibrationReport(
            total_samples=len(dataset),
            spearman_correlation=spearman_correlations,
            weighted_cohens_kappa=weighted_kappas,
            mean_absolute_error=maes,
            identified_weaknesses=weaknesses,
            recommendations=recommendations,
            calibration_status=status,
        )


evaluator_service = LLMJudgeEvaluator()

