# ADITSTUDIO — PHASE 3.2 IMPLEMENTATION REPORT
## Experiment Integrity, Foreign-Key Ordering & Metric Truthfulness

**Date:** November 23, 2026  
**Status:** COMPLETED & VERIFIED  
**Engineering Standards:** AGENTS.md — Zero Silent Failures, Zero Metric Fabrication, Explicit Authorization  
**Test Suite Pass Rate:** 85/85 tests passed (100%)  
**CI Gate Pass Rate:** 100% passed (2/2 sample cases evaluated)  
**Frontend Production Build:** PASSED (tsc && vite build in 1.55s)

---

## 1. Executive Summary

Phase 3.2 resolves the critical data integrity, transaction ordering, and metric accounting gaps identified during code review of Phase 3.1:
1. **Database Transaction & Foreign-Key Ordering**: Parent `BenchmarkExperiment` records are persisted with `status="RUNNING"` *before* any child `EvaluationRun` records are written. Actual `Series` and `Episode` records are created and committed in PostgreSQL *before* seeding lore records that reference them. `EvaluationRun` records now reliably store their corresponding `series_id` and `episode_id`. Status transitions cleanly to `COMPLETED` on success or `FAILED` on exception with database cleanup.
2. **RAG Experiment Isolation & Context Verification**: Proved that Variant A (RAG ON) retrieves the seeded lore into Planner and Writer, while Variant B (RAG OFF) receives strictly zero memory context. Added deterministic assertions verifying this invariant.
3. **Metric Truthfulness & Zero Fabrication**: Removed fabricated TTS cache hit rates (reported as `None` or `0.0`), counted real validation error records from graph state, tied pass rates strictly to `eval_res.passed` (including the safety threshold), distinguished `cases_improved`, `cases_regressed`, and `cases_unchanged`, and eliminated all unconditional claims in favor of dynamic, data-driven conclusions.
4. **Multi-Call Usage Accounting**: Extended `BaseLLMProvider` with cumulative usage history (`usage_history`) and `get_aggregated_usage()`. Tracks generation and judge tokens, latencies, models, providers, and costs separately.
5. **LIVE vs MOCK API Validation**: Added explicit mode parameters to `/benchmark` endpoint. Rejects missing LIVE credentials with an HTTP 400 Bad Request error without silently falling back to mock.
6. **Calibration Semantics**: Dimensions with sparse ratings return `None` rather than artificial zero correlations or zero MAE, preserving `PENDING_HUMAN_ANNOTATION`.

---

## 2. Key Changes & Architectural Implementation

### 2.1 Database Transaction Ordering & Foreign Keys (`backend/app/services/experiments.py`)
- **Parent Pre-persistence**: Inserted and committed `BenchmarkExperiment(id=experiment_id, user_id=resolved_user_id, status="RUNNING", ...)` before child variant loops execute. This ensures that foreign keys on `evaluation_runs.experiment_id` are always valid.
- **Episode & Series Provisioning**:
  ```python
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
  ```
- **Seeded Lore Foreign Keys**: Initial lore (`StoryBibleEntry`) rows are attached to `series_id` and `episode_id`, and committed to PostgreSQL *before* invoking LangGraph.
- **Child Run Associations**: `EvaluationRun` explicitly associates `series_id=series_id` and `episode_id=episode_id`.
- **Status Lifecycle & Rollback**:
  - On success: `exp_record.status = "COMPLETED"`, results summary committed.
  - On exception: `exp_record.status = "FAILED"`, error detail recorded in `results_summary`, committed, then re-raised.

### 2.2 RAG Experiment Isolation & Verification
- Extended `KathaEpisodeState` in `backend/app/agents/state.py` with:
  - `story_bible_context_planner: str | None`
  - `story_bible_context_writer: str | None`
- `planner_node` and `writer_node` record the retrieved lore context in state:
  ```python
  # In planner_node:
  return {
      "outline": outline,
      "story_bible_context_planner": story_bible_context,
      "status": "PLANNING_COMPLETED",
      "current_node": "planner",
  }
  ```
- In `_run_variant`:
  - If `retrieval_enabled=False` (RAG OFF): asserts `planner_rag_ctx == ""` and `writer_rag_ctx == ""` (raising `AssertionError` if any context leaked).
  - If `retrieval_enabled=True` (RAG ON): verifies seeded memories successfully reached the agent prompt.

### 2.3 Provider Usage Accounting Across Multiple Invocations (`backend/app/providers/base.py`)
- Enhanced `ProviderUsageMetadata` with `call_count: int = 1`.
- Added to `BaseLLMProvider`:
  - `self.usage_history: list[ProviderUsageMetadata] = []`
  - `record_usage(usage: ProviderUsageMetadata) -> None`
  - `get_aggregated_usage() -> ProviderUsageMetadata` (sums `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms` and computes composite `usage_type`)
  - `reset_usage() -> None`
- Generator and Judge usage are tracked and persisted separately in `EvaluationRun.node_latencies_json["usage_breakdown"]`:
  ```json
  {
    "generation": {
      "model": "gemini-1.5-pro",
      "provider": "gemini",
      "prompt_tokens": 1250,
      "completion_tokens": 420,
      "total_tokens": 1670,
      "latency_ms": 1420.5,
      "usage_type": "ACTUAL",
      "call_count": 6
    },
    "judge": {
      "model": "gemini-1.5-pro",
      "provider": "gemini",
      "prompt_tokens": 850,
      "completion_tokens": 180,
      "total_tokens": 1030,
      "latency_ms": 890.2,
      "usage_type": "ACTUAL",
      "call_count": 1
    }
  }
  ```

### 2.4 Metric Corrections & Dynamic Conclusions
- **No Fabricated TTS Rates**: `tts_cache_hit_rate` is set to `None` on `ExperimentVariantMetrics` and `0.0` on `EvaluationRun`, since text-generation benchmarks do not execute audio synthesis.
- **Measured Validation Failures**: Counts `len(final_state.get("errors", []))` from LangGraph state.
- **Safety-Aware Pass Rate**: Uses `eval_res.passed` directly, requiring composite $\ge 3.5$ and safety $\ge 4.0$.
- **Categorized Outcomes**:
  ```python
  improved_count = sum(1 for ra, rb in zip(runs_a, runs_b) if ra.composite_score > rb.composite_score + 0.05)
  regressed_count = sum(1 for ra, rb in zip(runs_a, runs_b) if ra.composite_score < rb.composite_score - 0.05)
  unchanged_count = len(cases) - (improved_count + regressed_count)
  ```
- **Dynamic Conclusions**: Unconditional assertions removed. Conclusions are generated based on whether `improved_count > regressed_count`, reporting inconclusive when evidence is insufficient or outcomes are balanced.

### 2.5 API Endpoints Hardening (`backend/app/api/v1/evaluations.py`)
- **`POST /benchmark`**: Added `mode: Literal["LIVE", "MOCK"] = "MOCK"`, `provider_a`, `provider_b`, `judge_model`, and `judge_provider`.
- **Fail-Fast Credential Verification**: If `mode="LIVE"` and `GEMINI_API_KEY` or `GROQ_API_KEY` are unset, returns HTTP 400 Bad Request with a clear message. Never silently switches to mock.
- **`POST /episodes/{id}/evaluate`**: Removed arbitrary percentage-based node latencies, set `tts_cache_hit_rate=0.0` (unmeasured), and determined `token_usage_type` from actual judge provider metadata.

### 2.6 Calibration Semantics (`backend/app/services/evaluator.py`)
- `run_calibration()` returns `None` for dimensions with fewer than 2 paired samples, rather than synthetic `0.0` correlations or `0.0` MAE.
- Preserves `PENDING_HUMAN_ANNOTATION` status when no genuine human annotations exist.

---

## 3. Test & Verification Evidence

### 3.1 Full Backend Test Suite
Executed all unit and integration tests across the entire repository:
```text
============================= test session starts ==============================
backend/tests/test_agents_pipeline.py .........                          [ 10%]
backend/tests/test_audio.py .....                                        [ 16%]
backend/tests/test_auth.py .......                                       [ 24%]
backend/tests/test_checkpointer.py ........                              [ 34%]
backend/tests/test_episodes.py ...                                       [ 37%]
backend/tests/test_evaluation.py .........................               [ 67%]
backend/tests/test_migrations.py .                                       [ 68%]
backend/tests/test_providers.py .....                                    [ 74%]
backend/tests/test_rag_postgres.py ...........                           [ 87%]
backend/tests/test_series.py ...                                         [ 90%]
backend/tests/test_story_bible.py ........                               [100%]
======================= 85 passed, 13 warnings in 13.77s =======================
```

### 3.2 Evaluation Suite (`test_evaluation.py`)
All 25 tests passed cleanly, specifically verifying:
1. `test_experiment_transaction_ordering_and_foreign_keys`: Parent `BenchmarkExperiment` persists with `status="COMPLETED"`, child `EvaluationRun` records reference existing `series_id` and `episode_id`, and initial lore records reference valid episode records.
2. `test_experiment_failure_status_rollback`: Proves that unhandled errors during variant execution update `BenchmarkExperiment` status to `"FAILED"`.
3. `test_rag_ablation_retrieval_isolation`: Confirms RAG ON receives seeded memories while RAG OFF receives zero Story Bible context.
4. `test_usage_aggregation_across_multiple_calls`: Proves `get_aggregated_usage()` accumulates token counts and latency across multiple LLM invocations.
5. `test_benchmark_api_live_mode_credential_validation`: Proves LIVE mode returns 400 on missing credentials, while MOCK mode succeeds.
6. `test_metric_truthfulness_no_fabricated_tts`: Confirms `tts_cache_hit_rate` is `None` on variant metrics and `0.0` on evaluation runs, and delta analysis includes `cases_improved`, `cases_regressed`, and `cases_unchanged`.

### 3.3 Production CI Evaluation Gate
```text
======================================================================
🚀 ADITSTUDIO — PRODUCTION CI EVALUATION GATE
======================================================================
Execution Mode:   MOCK (Deterministic CI Mock)
Provider / Model: mock / mock-model
Target Thresholds:
  • Min Pass Rate:        85.0%
  • Min Composite Score:  3.50 / 5.0
  • Min Safety Score:     4.00 / 5.0
  • Max Cost Per Ep:      $0.0500
======================================================================
Loaded 2 multilingual benchmark test cases.
  [1/2] Generating & Evaluating 'Purani Dilli Ki Dastak' (hinglish)... ✅ PASS (Score: 4.73)
  [2/2] Generating & Evaluating 'Indiranagar Pitch Deck' (hinglish)... ✅ PASS (Score: 4.73)

======================================================================
📊 EVALUATION GATE AUDIT RESULTS:
======================================================================
Pass Rate:        100.0%  (Required: >= 85.0%)
Avg Composite:    4.73  (Required: >= 3.50)
Avg Cost / Ep:    $0.00000  (Required: <= $0.0500)
Safety Violations: 0

✅ ALL EVALUATION GATES PASSED. CODE APPROVED FOR MERGE.
======================================================================
```

### 3.4 Frontend Production Build
```text
> katha-studio-frontend@0.1.0 build
> tsc && vite build
vite v5.4.21 building for production...
✓ 1588 modules transformed.
dist/index.html                   0.91 kB │ gzip:  0.56 kB
dist/assets/index-Dv1eWaaj.css   29.13 kB │ gzip:  5.64 kB
dist/assets/index-Bmm0qtEH.js   270.66 kB │ gzip: 74.38 kB
✓ built in 1.55s
```

---

## 4. Remaining Limitations

1. **Human Annotations**: The human ground-truth calibration dataset remains empty (`PENDING_HUMAN_ANNOTATION`), pending real double-blind annotator ratings. Synthetic fixtures remain strictly isolated from empirical calibration.
2. **Audio Phase Handoff**: Audio synthesis, TTS caching, and FFmpeg concatenations belong to Phase 4; text generation benchmarks appropriately leave `tts_cache_hit_rate` as `None` or `0.0`.
