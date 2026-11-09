# Katha Studio: REST API Reference & Contract Specification

> **FastAPI v1 Specification**  
> *Compliant with RFC 7807 Problem Details and OpenAPI 3.1.*

---

## 1. Authentication & Security (`/api/v1/auth`)

All secured endpoints require an `Authorization: Bearer <access_token>` header.

### `POST /api/v1/auth/register`
Create a new user account.
- **Request Body**:
  ```json
  {
    "email": "producer@katha.studio",
    "password": "StrongPassword123!",
    "full_name": "Vikram Seth"
  }
  ```
- **Response `201 Created`**:
  ```json
  {
    "id": "c1f7b02e-9d2a-4a61-b4f7-920f04e4c412",
    "email": "producer@katha.studio",
    "full_name": "Vikram Seth",
    "is_active": true,
    "created_at": "2026-11-10T02:00:00Z"
  }
  ```

### `POST /api/v1/auth/login`
Authenticate with credentials and obtain access + refresh JWTs.
- **Request Body**: `application/x-www-form-urlencoded` (`username`, `password`)
- **Response `200 OK`**:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1Ni...",
    "refresh_token": "eyJhbGciOiJIUzI1Ni...",
    "token_type": "bearer",
    "user": { ... }
  }
  ```

---

## 2. Series & Story Bible Management (`/api/v1/series`)

### `GET /api/v1/series`
List all series owned by the authenticated user.

### `POST /api/v1/series`
Create a new audio drama series.
- **Request Body**:
  ```json
  {
    "title": "Chambal Ki Goonj",
    "genre": "Historical Crime Drama",
    "logline": "A former dacoit returns to the ravines of Chambal 30 years later.",
    "target_language": "hindi"
  }
  ```

### `POST /api/v1/series/{series_id}/bible`
Add or update a persistent Story Bible fact entry.
- **Request Body**:
  ```json
  {
    "entity_type": "character",
    "entity_name": "Bhairav Singh",
    "content": "Legendary rifleman; lost his left eye in the 1982 encounter.",
    "metadata_json": { "vocal_archetype": "gruff_veteran", "allegiance": "rebel" }
  }
  ```

### `POST /api/v1/series/{series_id}/bible/search`
Perform hybrid vector + keyword memory retrieval.
- **Request Body**:
  ```json
  {
    "query": "Who is Bhairav Singh's rival?",
    "limit": 5,
    "retrieval_enabled": true
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "status": "RETRIEVAL_SUCCESS",
    "query": "Who is Bhairav Singh's rival?",
    "results": [
      {
        "entry": { ... },
        "score": 0.892,
        "retrieval_method": "hybrid_rrf"
      }
    ],
    "retrieval_enabled": true
  }
  ```

---

## 3. Episode Generation & SSE Streaming (`/api/v1/generation`)

### `POST /api/v1/generation/episodes/{episode_id}/generate`
Trigger asynchronous LangGraph pipeline execution.
- **Request Body**:
  ```json
  {
    "enable_critic": true,
    "enable_story_bible": true,
    "model_name": "gemini-1.5-pro",
    "max_revisions": 2
  }
  ```
- **Response `202 Accepted`**:
  ```json
  {
    "status": "PROCESSING",
    "episode_id": "ep_9876",
    "task_id": "task_12345",
    "stream_url": "/api/v1/generation/episodes/ep_9876/stream"
  }
  ```

### `GET /api/v1/generation/episodes/{episode_id}/stream`
Real-time Server-Sent Events (SSE) progress connection.
- **Headers**: `Accept: text/event-stream`
- **Event Stream**:
  ```
  event: progress
  data: {"node": "planner", "status": "completed", "progress_pct": 20}

  event: progress
  data: {"node": "writer", "status": "completed", "progress_pct": 50}

  event: progress
  data: {"node": "critic", "score": 4.6, "revisions": 0, "status": "passed"}

  event: complete
  data: {"episode_id": "ep_9876", "status": "READY"}
  ```

---

## 4. Audio Synthesis & Per-Line Editing (`/api/v1/audio`)

### `POST /api/v1/audio/episodes/{episode_id}/synthesize`
Synthesize all dialogue lines and assemble master audio track.
- **Response `200 OK`**:
  ```json
  {
    "episode_id": "ep_9876",
    "master_audio_url": "/audio_cache/episodes/ep_9876_master.mp3",
    "duration_seconds": 312.4,
    "cache_hit_rate": 0.82
  }
  ```

### `POST /api/v1/audio/lines/{line_id}/regenerate`
Regenerate a single dialogue line without rebuilding the entire episode.
- **Request Body**:
  ```json
  {
    "new_text": "Bhairav, yeh bandook ab nahi chalegi.",
    "voice_id": "voice_veteran_01",
    "speed": 1.0,
    "pitch": 0.0
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "line_id": "line_45",
    "audio_url": "/audio_cache/f7a1b8...mp3",
    "duration_seconds": 3.8
  }
  ```

---

## 5. Evaluations & Observability (`/api/v1/evaluations`)

### `GET /api/v1/evaluations/summary`
Get aggregated pass rates, latency percentiles, cost, and failure taxonomies.

### `POST /api/v1/evaluations/episodes/{episode_id}/evaluate`
Run the 5D LLM Judge against an episode script and persist metric trace.

### `POST /api/v1/evaluations/benchmark`
Run controlled A/B experiments (`critic_on_off`, `rag_ablation`, `model_comparison`).

### `GET /api/v1/evaluations/calibration`
Compute Spearman correlation, weighted Cohen's kappa, and MAE against 30 ground-truth human scripts.

---

## 6. Standard Error Response (RFC 7807)

```json
{
  "type": "https://errors.katha.studio/entity-not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "Episode with ID 'ep_9876' does not exist.",
  "error_code": "ENTITY_NOT_FOUND",
  "extras": { "entity_type": "Episode", "entity_id": "ep_9876" }
}
```

