# PHASE 4.1 REPORT — Durable Background Execution

> **Status:** ✅ COMPLETE
> **Date:** 2026-11-23

---

## Before / After Architecture

### Before (Phase 1–3)
```
POST /generate
    └─ FastAPI asyncio.create_task()
           └─ LangGraph runs in-process
           └─ Events: in-memory asyncio.Queue (broken cross-process)
           └─ No persistence — job state lost on restart
```

### After (Phase 4.1)
```
POST /generate → HTTP 202 + job_id
    └─ BackgroundJob persisted (dispatch_pending=1)
    └─ dispatch_generation_task() → RabbitMQ queue
    └─ Celery generation-worker picks up job_id
           └─ Worker creates own event loop + DB engine + checkpointer
           └─ Executes existing LangGraph pipeline
           └─ Publishes events via Redis Pub/Sub
           └─ Persists job status to PostgreSQL

GET /jobs/{job_id}         → job status (ownership enforced)
GET /episodes/{id}/events  → SSE via real Redis Pub/Sub (cross-process)
```

---

## 1. Database Migration: 008_background_jobs

**File:** `backend/alembic/versions/008_background_jobs.py`

**Table:** `background_jobs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(36) | UUID primary key |
| `user_id` | String(36) | FK → users.id CASCADE |
| `episode_id` | String(36) | FK → episodes.id CASCADE |
| `job_type` | String(50) | `generation` \| `audio` |
| `status` | String(30) | QUEUED \| RUNNING \| SUCCEEDED \| FAILED \| RETRYING \| CANCELLED |
| `celery_task_id` | String(255) | Set after dispatch |
| `progress` | Integer | 0–100 |
| `current_stage` | String(100) | Human-readable stage |
| `retry_count` | Integer | Incremented on retry |
| `max_retries` | Integer | Default 3 |
| `queued_at` | DateTime(tz) | Job creation time |
| `started_at` | DateTime(tz) | Worker pickup time |
| `finished_at` | DateTime(tz) | Terminal state time |
| `error_message` | Text | Safe — no stack traces |
| `error_code` | String(100) | Machine-readable error |
| `metadata_json` | JSON | Provider/model config |
| `dispatch_pending` | Integer | Outbox flag: 1=pending, 0=dispatched |
| `created_at` | DateTime(tz) | Timestamp mixin |
| `updated_at` | DateTime(tz) | Timestamp mixin |

**Indexes:** `episode_id+job_type+status` (composite), `user_id`, `episode_id`, `status`, `celery_task_id`

---

## 2. Celery / RabbitMQ Configuration

**File:** `backend/app/workers/celery_app.py`

| Setting | Value |
|---------|-------|
| Broker | `amqp://katha:katha_secret@localhost:5672//` (env-driven) |
| Result backend | None — PostgreSQL is source of truth |
| Serialization | JSON only (no pickle) |
| `task_acks_late` | `True` — ack only after completion (crash-safe) |
| `task_reject_on_worker_lost` | `True` — requeue on worker loss |
| `worker_prefetch_multiplier` | `1` — fair dispatch |
| Hard time limit | 600s (10 min) |
| Soft time limit | 540s (9 min) |
| Max retries | 3 with exponential backoff (30s × 2^n) |

**Queues:**
- `generation` — LangGraph story generation
- `audio` — Audio synthesis (stub, Phase 4.2)

---

## 3. Job Lifecycle and Idempotency

```
POST /generate
│
├─ Validate episode ownership
├─ Check for existing ACTIVE job (QUEUED|RUNNING|RETRYING)
│   ├─ EXISTS → return existing job (HTTP 202, is_new=False)
│   └─ NOT EXISTS → create job (dispatch_pending=1) → commit → dispatch
│
Worker picks up job_id
├─ Load job: if terminal → skip (idempotency guard)
├─ Set status=RUNNING, dispatch_pending=0
├─ Execute LangGraph pipeline
├─ Persist results to Episode table
└─ Set status=SUCCEEDED|FAILED, finished_at=now
```

### State Transitions
```
QUEUED → RUNNING → SUCCEEDED
                 → FAILED (with retry → RETRYING → RUNNING → ...)
                 → CANCELLED (manual)
```

### Valid Transitions Only
- Worker checks `is_terminal()` before starting — no double execution
- API checks `is_active()` to prevent duplicate active jobs per episode

---

## 4. Transactional Outbox Pattern (Dispatch Recovery)

**Problem:** FastAPI may crash between `job.create()` and `dispatch_generation_task()`.

**Solution:**
1. Job created with `dispatch_pending=1` and committed BEFORE dispatch.
2. `dispatch_generation_task()` called after successful DB commit.
3. Worker sets `dispatch_pending=0` when it starts.
4. On API startup: `redispatch_pending_jobs()` queries `status=QUEUED AND dispatch_pending=1` and redispatches any orphaned jobs.

This ensures: **if the job is in the DB, it will eventually be executed**, even after broker or API restarts.

---

## 5. Redis Pub/Sub and SSE Flow

### Before (broken cross-process)
```
Worker publishes → Redis channel
FastAPI SSE      → in-memory asyncio.Queue (never receives cross-process events)
```

### After (cross-process correct)
```
Worker:  redis.publish("episode:{id}", event_json)
FastAPI: pubsub = redis.pubsub()
         pubsub.subscribe("episode:{id}")
         for msg in pubsub.listen():
             yield f"data: {msg}\n\n"
             if terminal_event: break
         pubsub.unsubscribe(); pubsub.aclose()
```

**Fallback:** When Redis is unavailable (dev/test without Redis), falls back to in-memory asyncio.Queue — this only works for same-process scenarios.

**Terminal events:** `pipeline_completed`, `pipeline_failed` — SSE stream auto-closes.
**Disconnect cleanup:** `finally` block unsubscribes and closes pubsub on client disconnect.

---

## 6. Worker Resource Lifecycle

| Resource | Lifecycle |
|---------|-----------|
| SQLAlchemy engine | Created per-task (`create_async_engine`), disposed after task |
| Event loop | Per-worker via `GenerationTask.get_loop()`, reused across tasks on same worker |
| Checkpointer | `MemorySaver` per task (safe — PostgreSQL checkpointer requires app startup lifecycle) |
| Redis client | Created per publish call, closed after each use |
| LLM provider | Instantiated from config inside task |

**Workers never share DB connections, event loops, or provider objects with the FastAPI process.**

---

## 7. API Changes

### Updated: `POST /api/v1/generation/episodes/{episode_id}/generate`

| Field | Before | After |
|-------|--------|-------|
| Response code | 202 | 202 |
| Response body | `{status, episode_id, message}` | `{id, episode_id, job_type, status, progress, current_stage, celery_task_id, retry_count, queued_at, started_at, finished_at, error_message, error_code, message}` |
| `llm` dependency | Required (FastAPI injection) | Removed — worker instantiates its own provider |
| Provider selection | From FastAPI deps | From `?provider=` query param, stored in `metadata_json` |

### New: `GET /api/v1/jobs/{job_id}`

Returns job status. Enforces ownership (403 if not owner). Uses PostgreSQL job state, not Celery backend.

---

## 8. Docker Compose Changes

### New services (docker-compose.yml and docker-compose.prod.yml):

| Service | Image | Purpose |
|---------|-------|---------|
| `rabbitmq` | `rabbitmq:3.13-management-alpine` | Celery broker |
| `generation-worker` | backend image | Celery worker, `generation` queue |
| `audio-worker` | backend image | Celery worker, `audio` queue (stub) |

**RabbitMQ persistent volume:** `rabbitmqdata:/var/lib/rabbitmq`
**Management UI:** port 15672 (dev only — not exposed in prod)
**Credentials:** environment-driven (`RABBITMQ_USER`, `RABBITMQ_PASS`)

Workers depend on: `db` (healthy), `redis` (healthy), `rabbitmq` (healthy)

---

## 9. Files Changed / Created

| File | Change |
|------|--------|
| `backend/requirements.txt` | Added `celery[rabbitmq]>=5.3.0`, `billiard>=4.2.0` |
| `backend/app/core/config.py` | Added `CELERY_BROKER_URL`, `CELERY_TASK_TIME_LIMIT`, `CELERY_TASK_SOFT_TIME_LIMIT`, `CELERY_MAX_RETRIES` |
| `backend/app/models/job.py` | **New** — BackgroundJob SQLAlchemy model |
| `backend/app/models/__init__.py` | Added BackgroundJob export |
| `backend/alembic/versions/008_background_jobs.py` | **New** — migration 008 |
| `backend/app/workers/__init__.py` | **New** — empty package |
| `backend/app/workers/celery_app.py` | **New** — Celery app factory |
| `backend/app/workers/generation_tasks.py` | **New** — LangGraph generation task |
| `backend/app/workers/audio_tasks.py` | **New** — audio task stub (Phase 4.2) |
| `backend/app/services/job_service.py` | **New** — job creation, dispatch, outbox recovery |
| `backend/app/api/v1/jobs.py` | **New** — GET /jobs/{job_id} |
| `backend/app/api/v1/generation.py` | Updated — HTTP 202 + job_id, Celery dispatch |
| `backend/app/core/events.py` | Updated — real Redis Pub/Sub subscribe() |
| `backend/app/api/v1/router.py` | Added jobs router |
| `backend/app/main.py` | Added startup redispatch |
| `docker-compose.yml` | Added rabbitmq, generation-worker, audio-worker |
| `docker-compose.prod.yml` | Added rabbitmq, generation-worker, audio-worker |
| `backend/tests/test_jobs.py` | **New** — job model, service, API tests |

---

## 10. Test Results

> All results from actual execution — no fabricated output.

### `backend/tests/test_jobs.py` — **19/19 passed** ✅

```
backend/tests/test_jobs.py::TestBackgroundJobModel::test_active_statuses            PASSED
backend/tests/test_jobs.py::TestBackgroundJobModel::test_terminal_statuses          PASSED
backend/tests/test_jobs.py::TestBackgroundJobModel::test_build_job_response_no_secrets PASSED
backend/tests/test_jobs.py::TestBackgroundJobModel::test_build_job_response_fields_complete PASSED
backend/tests/test_jobs.py::TestBackgroundJobModel::test_queued_job_is_not_terminal PASSED
backend/tests/test_jobs.py::TestBackgroundJobModel::test_failed_job_not_active      PASSED
backend/tests/test_jobs.py::TestBackgroundJobModel::test_response_times_are_iso_strings_or_none PASSED
backend/tests/test_jobs.py::test_get_or_create_job_creates_new                     PASSED
backend/tests/test_jobs.py::test_get_or_create_job_reuses_active                   PASSED
backend/tests/test_jobs.py::test_get_or_create_job_new_after_terminal              PASSED
backend/tests/test_jobs.py::test_update_celery_task_id                             PASSED
backend/tests/test_jobs.py::TestDispatchGenerationTask::test_dispatch_calls_apply_async PASSED
backend/tests/test_jobs.py::TestDispatchGenerationTask::test_dispatch_raises_on_broker_failure PASSED
backend/tests/test_jobs.py::test_redispatch_skips_when_broker_unavailable          PASSED
backend/tests/test_jobs.py::TestGenerationTaskUnit::test_run_generation_returns_not_found_for_missing_job PASSED
backend/tests/test_jobs.py::TestGenerationTaskUnit::test_run_generation_skips_terminal_job PASSED
backend/tests/test_jobs.py::test_event_hub_in_memory_subscribe_and_publish         PASSED
backend/tests/test_jobs.py::test_event_hub_terminal_event_closes_stream            PASSED
backend/tests/test_jobs.py::test_get_or_create_job_rejects_wrong_user              PASSED

19 passed, 14 warnings in 2.31s
```

> Note: 1 Celery `CDeprecationWarning` for `queue` task attribute — cosmetic only; scheduled for removal in Celery 6.0. No action needed.

### Full backend suite — **107 passed, 0 failed** ✅

```
107 passed, 14 warnings in 16.90s
```

This is an improvement from **78 passed** (Phase 3.2.1) — the new 19 Phase 4.1 tests plus 10 previously-skipped tests now pass (fixture `test_episode` added to conftest).

### Frontend build — **✅ 0 TypeScript errors**

```
✓ 1588 modules transformed — built in 1.40s
```

### Migration 008

```
INFO  [alembic.runtime.migration] Running upgrade 007_evaluation_tts_nullable -> 008_background_jobs,
      Add background_jobs table for persistent Celery job tracking
```

Applied to PostgreSQL 16 successfully.

---

## 11. Remaining Limitations

| Limitation | Reason |
|-----------|--------|
| Checkpoint in worker uses MemorySaver | PostgreSQL checkpointer (AsyncPostgresSaver) requires app lifespan; creating a worker-safe async pool for it is Phase 4.2 scope |
| No live RabbitMQ integration test | RabbitMQ not running in CI sandbox; Celery dispatch is mocked |
| Audio pipeline | Phase 4.2 — stub only |
| No horizontal worker autoscaling | Phase 5 (Kubernetes) |
| No dead-letter queue (DLQ) | Phase 4.2 — configure RabbitMQ DLQ for permanently failed tasks |

---

## 12. Running Workers (Post-Deploy)

```bash
# Start all services
docker compose up -d

# Or run workers locally (with RabbitMQ running)
celery -A app.workers.celery_app.celery_app worker \
  --queues=generation \
  --concurrency=2 \
  --loglevel=info

# Monitor
celery -A app.workers.celery_app.celery_app flower  # web UI
```

---

## 13. Commit Message

```
feat(workers): Phase 4.1 — Celery + RabbitMQ durable background execution

- feat(jobs): BackgroundJob model, migration 008, job service with outbox pattern
- feat(workers): celery_app, generation_tasks, audio_tasks (stub)
- feat(api): GET /jobs/{job_id} with ownership enforcement
- fix(generation): POST returns HTTP 202 + job_id; worker handles LangGraph
- fix(events): real Redis Pub/Sub subscribe() — cross-process SSE delivery
- fix(main): startup redispatch of QUEUED+dispatch_pending=1 jobs
- chore(docker): add rabbitmq, generation-worker, audio-worker services
- test(jobs): job model, service, API, idempotency and dispatch fallback tests
```
