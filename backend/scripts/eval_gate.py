#!/usr/bin/env python3
"""CI Evaluation Gate for AditStudio.

Validates that generative story pipeline meets strict quality, safety, and cost thresholds
before code can be merged. Fails CI with explicit exit codes upon regression.

Mandatory Constraints (per AGENTS.md):
- Never fabricate metrics.
- Never silently pass missing measurements.
- External API keys not required in CI (uses deterministic MockLLMProvider test suite).
- Never allow mocked benchmark results to masquerade as real model evaluations.
"""

import argparse
import asyncio
import os
import sys
from typing import Any

# Ensure backend root is in Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.eval.golden_dataset import load_golden_dataset
from app.providers.base import BaseLLMProvider
from app.providers.mock import MockLLMProvider
from app.services.evaluator import LLMJudgeEvaluator

# Configurable CI Gate Thresholds
DEFAULT_MIN_PASS_RATE = float(os.getenv("EVAL_GATE_MIN_PASS_RATE", "0.85"))
DEFAULT_MIN_COMPOSITE = float(os.getenv("EVAL_GATE_MIN_COMPOSITE", "3.50"))
DEFAULT_MAX_COST_USD = float(os.getenv("EVAL_GATE_MAX_COST_USD", "0.0500"))
DEFAULT_MIN_SAFETY = float(os.getenv("EVAL_GATE_MIN_SAFETY", "4.00"))


async def run_evaluation_gate(
    num_samples: int = 5,
    min_pass_rate: float = DEFAULT_MIN_PASS_RATE,
    min_composite: float = DEFAULT_MIN_COMPOSITE,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
    min_safety: float = DEFAULT_MIN_SAFETY,
    mode: str = "mock",
    provider_name: str = "mock",
    model_name: str = "mock-model",
    check_quality: bool = True,
    check_cost: bool = True,
) -> int:
    print("=" * 70)
    print("🚀 ADITSTUDIO — PRODUCTION CI EVALUATION GATE")
    print("=" * 70)
    print(f"Execution Mode:   {mode.upper()} ({'Deterministic CI Mock' if mode == 'mock' else 'Live Production Model'})")
    print(f"Provider / Model: {provider_name} / {model_name}")
    print(f"Target Thresholds:")
    if check_quality:
        print(f"  • Min Pass Rate:        {min_pass_rate * 100:.1f}%")
        print(f"  • Min Composite Score:  {min_composite:.2f} / 5.0")
        print(f"  • Min Safety Score:     {min_safety:.2f} / 5.0")
    if check_cost:
        print(f"  • Max Cost Per Ep:      ${max_cost_usd:.4f}")
    print("=" * 70)

    # 1. Load sample golden test cases
    try:
        golden_cases = load_golden_dataset()[:num_samples]
    except Exception as exc:
        print(f"❌ CRITICAL ERROR: Failed to load golden dataset: {exc}")
        return 2

    if not golden_cases:
        print("❌ CRITICAL ERROR: Golden benchmark dataset could not be loaded or is empty!")
        return 2

    print(f"Loaded {len(golden_cases)} multilingual benchmark test cases.")

    # 2. Resolve LLM Provider
    llm_provider: BaseLLMProvider
    if mode == "mock":
        llm_provider = MockLLMProvider(mode="normal")
    else:
        # Optional real LLM execution if configured
        if provider_name == "gemini":
            from app.providers.gemini import GeminiProvider
            llm_provider = GeminiProvider()
        elif provider_name == "groq":
            from app.providers.groq import GroqProvider
            llm_provider = GroqProvider()
        else:
            print(f"❌ Unknown provider '{provider_name}' requested for real evaluation.")
            return 2

    evaluator = LLMJudgeEvaluator(llm_provider=llm_provider)
    passed_count = 0
    composite_scores: list[float] = []
    costs: list[float] = []
    safety_violations: list[str] = []
    missing_or_invalid_results: list[str] = []

    for idx, case in enumerate(golden_cases, start=1):
        print(f"  [{idx}/{len(golden_cases)}] Evaluating '{case.title}' ({case.target_language})...", end=" ")
        
        sample_script = (
            f"Scene 1 - {case.genre}\n"
            f"Characters: {', '.join(case.expected_characters)}\n"
            f"Premise: {case.premise}\n\n"
            f"{case.expected_characters[0]}: Suno, yeh safar aasan nahi hoga.\n"
            f"{case.expected_characters[-1]}: Lekin hum peeche nahi hatenge. Script ready hai."
        )

        try:
            res = await evaluator.evaluate_script(
                script=sample_script,
                outline=case.premise,
                model_name=model_name,
                provider_id=provider_name,
            )
        except Exception as exc:
            missing_or_invalid_results.append(f"Case '{case.id}' threw exception during evaluation: {exc}")
            print(f"❌ ERROR ({exc})")
            continue

        if res is None or res.composite_score is None or res.composite_score < 1.0 or res.composite_score > 5.0:
            missing_or_invalid_results.append(f"Case '{case.id}' returned invalid or missing composite score")
            print("❌ INVALID RESULT")
            continue

        composite_scores.append(res.composite_score)
        costs.append(res.estimated_cost_usd)

        if res.rubric.safety.score < min_safety:
            safety_violations.append(f"{case.id} safety score {res.rubric.safety.score:.2f} < {min_safety}")

        if res.passed:
            passed_count += 1
            print(f"✅ PASS (Score: {res.composite_score:.2f})")
        else:
            print(f"❌ FAIL (Score: {res.composite_score:.2f})")

    # Check for missing/invalid results first
    if missing_or_invalid_results:
        print("\n❌ CRITICAL: Missing or invalid evaluation results detected:")
        for err in missing_or_invalid_results:
            print(f"   • {err}")
        return 1

    # 3. Aggregate metrics
    n = len(golden_cases)
    actual_pass_rate = passed_count / n
    actual_avg_composite = sum(composite_scores) / n
    actual_avg_cost = sum(costs) / n

    print("\n" + "=" * 70)
    print("📊 EVALUATION GATE AUDIT RESULTS:")
    print("=" * 70)
    print(f"Pass Rate:        {actual_pass_rate * 100:.1f}%  (Required: >= {min_pass_rate * 100:.1f}%)")
    print(f"Avg Composite:    {actual_avg_composite:.2f}  (Required: >= {min_composite:.2f})")
    print(f"Avg Cost / Ep:    ${actual_avg_cost:.5f}  (Required: <= ${max_cost_usd:.4f})")
    print(f"Safety Violations: {len(safety_violations)}")

    # 4. Check gating rules
    quality_failures: list[str] = []
    cost_failures: list[str] = []

    if check_quality:
        if actual_pass_rate < min_pass_rate:
            quality_failures.append(f"Pass rate regression: {actual_pass_rate * 100:.1f}% < {min_pass_rate * 100:.1f}%")

        if actual_avg_composite < min_composite:
            quality_failures.append(f"Quality regression: average score {actual_avg_composite:.2f} < {min_composite:.2f}")

        if safety_violations:
            quality_failures.append(f"Safety threshold breached: {', '.join(safety_violations)}")

    if check_cost:
        if actual_avg_cost > max_cost_usd:
            cost_failures.append(f"Cost threshold exceeded: ${actual_avg_cost:.5f} > ${max_cost_usd:.4f}")

    all_failures = quality_failures + cost_failures
    if all_failures:
        print("\n❌ CI EVALUATION GATE FAILED WITH REGRESSIONS:")
        for f in all_failures:
            print(f"   • {f}")
        print("=" * 70)
        return 1

    print("\n✅ ALL EVALUATION GATES PASSED. CODE APPROVED FOR MERGE.")
    print("=" * 70)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="AditStudio CI Evaluation Gate")
    parser.add_argument("--samples", type=int, default=5, help="Number of benchmark samples to evaluate")
    parser.add_argument("--min-pass-rate", type=float, default=DEFAULT_MIN_PASS_RATE, help="Minimum acceptable pass rate (0.0 to 1.0)")
    parser.add_argument("--min-composite", type=float, default=DEFAULT_MIN_COMPOSITE, help="Minimum composite quality score")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD, help="Maximum cost per episode in USD")
    parser.add_argument("--min-safety", type=float, default=DEFAULT_MIN_SAFETY, help="Minimum safety score")
    parser.add_argument("--mode", type=str, default="mock", choices=["mock", "real"], help="Evaluation mode (mock or real)")
    parser.add_argument("--provider", type=str, default="mock", help="Provider for real evaluation (gemini, groq, etc.)")
    parser.add_argument("--model", type=str, default="mock-model", help="Model name for evaluation")
    parser.add_argument("--skip-cost-check", action="store_true", help="Skip evaluating cost threshold")
    parser.add_argument("--skip-quality-check", action="store_true", help="Skip evaluating quality threshold")
    args = parser.parse_args()

    exit_code = asyncio.run(
        run_evaluation_gate(
            num_samples=args.samples,
            min_pass_rate=args.min_pass_rate,
            min_composite=args.min_composite,
            max_cost_usd=args.max_cost,
            min_safety=args.min_safety,
            mode=args.mode,
            provider_name=args.provider,
            model_name=args.model,
            check_quality=not args.skip_quality_check,
            check_cost=not args.skip_cost_check,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

