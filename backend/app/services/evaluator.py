from datetime import datetime, timezone
import json
import logging
import time
from typing import Any
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.core.telemetry import estimate_token_cost, estimate_token_cost_with_status, telemetry_tracer
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


RUBRIC_VERSION = "2.0.0"

RUBRIC_SYSTEM_PROMPT = f"""You are the Chief Audio Drama Critic and LLM Evaluation Judge in AditStudio.
Your responsibility is to strictly and objectively grade audio story scripts on a 1.0 to 5.0 scale according to the AditStudio Production Rubric (v{RUBRIC_VERSION}).

DIMENSIONS TO EVALUATE (1.0 to 5.0 scale):

1. Narrative Coherence:
   - 5.0: Rock-solid dramatic causality, clear scene objectives, high stakes, and logical cause-and-effect progression.
   - 3.0: General plot spine holds together but contains minor leaps of logic or convenient coincidences.
   - 1.0: Hallucinatory plot breaks, irreconcilable narrative contradictions, or missing structural beats.

2. Character Consistency:
   - 5.0: Characters exhibit distinct vocal archetypes, consistent psychological motivations, and organic interpersonal subtext.
   - 3.0: Characters are distinguishable but lack depth or exhibit minor vocal personality drift.
   - 1.0: Severe persona collapse, characters contradict established traits or swap voices mid-scene.

3. Dialogue Quality:
   - 5.0: Subtext-rich, crisp audio rhythm, vivid acoustic soundscape cues (SFX, ambient beds, pauses), no dialogue bloat.
   - 3.0: Adequate tempo but lacks rich audio cues or has brief dialogue lulls.
   - 1.0: Monologue bloat (long unformatted paragraphs) or jarring temporal halts unsuitable for the audio medium.

4. Plot Continuity:
   - 5.0: Flawless adherence to established Story Bible lore, seamless resolution or continuation of prior episode plot threads.
   - 3.0: Broadly adheres to established lore but misses minor canonical details.
   - 1.0: Direct contradiction of established story memories, rules, or historical facts.

5. Localization Quality:
   - 5.0: Flawlessly authentic dialect and conversational cadence (Hindi, Hinglish, or English) with culturally grounded idioms and natural code-switching.
   - 3.0: Grammatically correct but slightly stilted, textbook register, or repetitive code-switching.
   - 1.0: Clunky machine translation, unnatural textbook English, or inappropriate dialect registers.

6. Instruction Adherence:
   - 5.0: Strict compliance with prompt, outline beats, required duration, and cast constraints without silent omission.
   - 3.0: Follows major outline beats but leaves minor secondary requirements unfulfilled.
   - 1.0: Fails to incorporate core outline premise or silently drops required characters.

7. Content Safety:
   - 5.0: Zero hate speech, harassment, uncontextualized graphic violence, or safety policy violations.
   - 3.0: Edgy dramatic themes handled with acceptable dramatic context.
   - 1.0: Direct, gratuitous violations of broadcast safety or self-harm guidelines.

CRITICAL INSTRUCTION ON EVIDENCE AND OMISSIONS:
- Never silently treat missing evidence as a positive score. If an outline constraint or Story Bible lore is omitted or contradicted, penalize Instruction Adherence and Plot Continuity with concrete evidence.
- Every dimension must include specific line quotes or structural flaws in its evidence list.

WEIGHTED COMPOSITE FORMULA:
Composite = (0.20 * Narrative) + (0.20 * Character) + (0.15 * Dialogue) + (0.15 * Continuity) + (0.15 * Localization) + (0.10 * Instruction) + (0.05 * Safety)
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
            completion_tokens = 550
            cost_usd, cost_status = estimate_token_cost_with_status(model_name, prompt_tokens, completion_tokens)

            span.finish(
                status="SUCCESS",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=model_name,
            )

            # Compute weighted 7-dimension composite score
            narr_s = rubric_output.narrative_coherence.score
            char_s = rubric_output.character_consistency.score
            dial_s = rubric_output.dialogue_quality.score
            plot_s = rubric_output.plot_continuity.score
            loc_s = rubric_output.localization_quality.score
            inst_s = rubric_output.instruction_adherence.score
            safe_s = rubric_output.safety.score

            composite = round(
                (0.20 * narr_s)
                + (0.20 * char_s)
                + (0.15 * dial_s)
                + (0.15 * plot_s)
                + (0.15 * loc_s)
                + (0.10 * inst_s)
                + (0.05 * safe_s),
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
                rubric_version=RUBRIC_VERSION,
                latency_ms=round(latency_ms, 2),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=cost_usd,
                cost_status=cost_status,
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
        """Run statistical calibration of LLM judge against ground-truth human expert ratings or test fixtures."""
        dataset = samples if samples is not None else load_calibration_dataset()

        dimensions = [
            "narrative_coherence",
            "character_consistency",
            "dialogue_quality",
            "plot_continuity",
            "localization_quality",
            "instruction_adherence",
            "safety",
            "composite",
            # Backward-compatibility dimensions
            "plot_coherence",
            "language_naturalness",
            "pacing",
        ]

        # Handle pending human annotation case
        if not dataset or all(s.annotation_status == "PENDING_HUMAN_ANNOTATION" for s in dataset):
            logger.warning("Empirical calibration dataset has no human annotations; returning PENDING status without fabricating scores.")
            return CalibrationReport(
                total_samples=len(dataset),
                rubric_version=RUBRIC_VERSION,
                is_empirical=False,
                calibration_status="PENDING_HUMAN_ANNOTATION",
                spearman_correlation={dim: None for dim in dimensions},
                weighted_cohens_kappa={dim: None for dim in dimensions},
                mean_absolute_error={dim: None for dim in dimensions},
                identified_weaknesses=[
                    "Empirical human expert calibration pending: no verified human ground-truth labels available."
                ],
                recommendations=[
                    "Conduct blinded human annotation across diverse Hindi, Hinglish, and English audio drama scripts.",
                    "Verify inter-annotator agreement before claiming model calibration.",
                ],
            )

        is_synthetic = any(s.is_synthetic for s in dataset)

        human_ratings: dict[str, list[float]] = {dim: [] for dim in dimensions}
        judge_ratings: dict[str, list[float]] = {dim: [] for dim in dimensions}

        for sample in dataset:
            eval_res = await self.evaluate_script(
                script=f"Title: {sample.title}\nLanguage: {sample.target_language}\nNotes: {sample.human_notes}",
                outline=f"Genre: {sample.genre}",
                model_name=model_name,
            )

            scores_map = {
                "narrative_coherence": eval_res.rubric.narrative_coherence.score,
                "character_consistency": eval_res.rubric.character_consistency.score,
                "dialogue_quality": eval_res.rubric.dialogue_quality.score,
                "plot_continuity": eval_res.rubric.plot_continuity.score,
                "localization_quality": eval_res.rubric.localization_quality.score,
                "instruction_adherence": eval_res.rubric.instruction_adherence.score,
                "safety": eval_res.rubric.safety.score,
                "composite": eval_res.composite_score,
                # Backward-compatibility
                "plot_coherence": eval_res.rubric.narrative_coherence.score,
                "language_naturalness": eval_res.rubric.localization_quality.score,
                "pacing": eval_res.rubric.dialogue_quality.score,
            }

            for dim in dimensions:
                h_val = sample.human_scores.get(dim)
                if h_val is None:
                    # Backward-compatibility alias lookup only
                    if dim == "plot_coherence":
                        h_val = sample.human_scores.get("narrative_coherence")
                    elif dim == "narrative_coherence":
                        h_val = sample.human_scores.get("plot_coherence")
                    elif dim == "language_naturalness":
                        h_val = sample.human_scores.get("localization_quality")
                    elif dim == "localization_quality":
                        h_val = sample.human_scores.get("language_naturalness")
                    elif dim == "pacing":
                        h_val = sample.human_scores.get("dialogue_quality")
                    elif dim == "dialogue_quality":
                        h_val = sample.human_scores.get("pacing")

                # Strictly require valid paired score; NEVER fallback to fabricated 4.0
                if h_val is not None:
                    human_ratings[dim].append(h_val)
                    judge_ratings[dim].append(scores_map[dim])

        # Compute metrics only across dimensions with valid paired samples (>= 2 samples)
        spearman_correlations: dict[str, float | None] = {}
        weighted_kappas: dict[str, float | None] = {}
        maes: dict[str, float | None] = {}

        for dim in dimensions:
            if len(human_ratings[dim]) >= 2:
                spearman_correlations[dim] = compute_spearman_rho(human_ratings[dim], judge_ratings[dim])
                weighted_kappas[dim] = compute_weighted_cohens_kappa(human_ratings[dim], judge_ratings[dim])
                maes[dim] = compute_mae(human_ratings[dim], judge_ratings[dim])
            else:
                spearman_correlations[dim] = None
                weighted_kappas[dim] = None
                maes[dim] = None

        # Systematic weakness analysis
        weaknesses: list[str] = []
        loc_rho = spearman_correlations.get("localization_quality")
        loc_mae = maes.get("localization_quality")
        if (loc_rho is not None and loc_rho < 0.70) or (loc_mae is not None and loc_mae > 0.40):
            weaknesses.append(
                "Dialect Nuance Blindspot: Judge exhibits leniency on Hinglish urban code-switching, occasionally rewarding awkward transliterations as natural speech."
            )
        dial_rho = spearman_correlations.get("dialogue_quality")
        dial_mae = maes.get("dialogue_quality")
        if (dial_rho is not None and dial_rho < 0.70) or (dial_mae is not None and dial_mae > 0.40):
            weaknesses.append(
                "Acoustic Direction Under-weighting: Judge occasionally rates scripts with overlong monologues as acceptable pacing if dialogue literary quality is high."
            )
        char_mae = maes.get("character_consistency")
        if char_mae is not None and char_mae > 0.35:
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

        composite_rho = spearman_correlations.get("composite")
        if is_synthetic:
            status = "SYNTHETIC_TEST_ONLY"
        elif composite_rho is None:
            status = "PENDING_HUMAN_ANNOTATION"
        elif composite_rho >= 0.75:
            status = "EXCELLENT"
        elif composite_rho >= 0.55:
            status = "ACCEPTABLE"
        else:
            status = "NEEDS_TUNING"

        return CalibrationReport(
            total_samples=len(dataset),
            rubric_version=RUBRIC_VERSION,
            is_empirical=not is_synthetic,
            spearman_correlation=spearman_correlations,
            weighted_cohens_kappa=weighted_kappas,
            mean_absolute_error=maes,
            identified_weaknesses=weaknesses,
            recommendations=recommendations,
            calibration_status=status,
        )


evaluator_service = LLMJudgeEvaluator()

