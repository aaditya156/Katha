# AGENTS.md — Katha Studio Engineering Guidelines & Rules of Engagement

> **Operational Standard for AI Agents and Engineers Collaborating on Katha Studio**  
> *Engineering rigor, schema enforceability, asynchronous safety, and zero silent failures.*

---

## 1. Core Engineering Philosophies

### 1.1 The "No-Silent-Failure" Principle (CRITICAL)
In an agentic audio pipeline, silent failures cause disastrous compounding errors: hallucinated script lines lead to wasted TTS credits, malformed audio leads to corrupt FFmpeg outputs, and unhandled exceptions leave frontend clients hanging indefinitely.

**Mandatory Rules:**
1. **Never swallow exceptions**:
   ```python
   # ❌ FORBIDDEN:
   try:
       result = await tts_client.synthesize(line.text)
   except Exception:
       pass  # or returning empty bytes / None
   
   # ✅ MANDATORY:
   try:
       result = await tts_client.synthesize(line.text)
   except TTSProviderError as exc:
       logger.error(
           "TTS synthesis failed for line",
           extra={"line_id": line.id, "voice_id": line.voice_id, "error": str(exc)},
           exc_info=True,
       )
       raise PipelineExecutionError(f"Line {line.id} synthesis failed: {exc}") from exc
   ```
2. **Explicit Error States in LangGraph**:
   - The graph state must include an `errors: list[GraphErrorRecord]` field.
   - If an agent node encounters a recoverable issue, it logs the structured error into `errors`. If unrecoverable, it sets state status to `FAILED`, raises an explicit exception, and emits an error event over the SSE bus.
3. **Never synthesize silence or mock audio without explicit flags**:
   - Audio files must be validated for minimum size (> 100 bytes) and valid audio container headers before saving or passing to FFmpeg.
4. **Structured HTTP Responses**:
   - Every API error must return a standard RFC 7807 Problem Details JSON format containing `type`, `title`, `status`, `detail`, and `error_code`.

---

## 2. Coding Standards & Architecture Rules

### 2.1 Backend (Python 3.11+ / FastAPI / SQLAlchemy Async)
1. **Type Annotations**:
   - 100% type coverage for public functions, methods, and API routes. Use `mypy --strict`.
   - Never use `Any` when a generic, Union, or TypedDict can be defined.
2. **Data Modeling & Validation (Pydantic v2)**:
   - Use Pydantic v2 `BaseModel` with `model_config = ConfigDict(strict=True, frozen=True)` for domain events and schemas.
   - All LLM agent outputs must use structured output validation (`client.beta.chat.completions.parse` or LangChain's `with_structured_output(Schema)`).
   - If parsing fails, trigger an explicit schema-repair retry or abort with a clear diagnostic error. Never fallback to guessing with regex.
3. **Asynchronous Execution & Concurrency**:
   - Never block the asyncio event loop with CPU-bound or disk I/O tasks.
   - Run FFmpeg commands and CPU-heavy audio manipulations using `asyncio.to_thread()` or dedicated subprocess executors.
   - Use `httpx.AsyncClient` for all outbound HTTP requests with explicit timeouts (`connect=5.0`, `read=30.0`).
4. **Database & Transactions**:
   - Use async SQLAlchemy 2.0 sessions (`AsyncSession`) with `async with session.begin():` blocks.
   - Avoid N+1 queries by using `selectinload` or `joinedload`.
   - Database migrations must be managed via Alembic; raw DDL execution in application code is strictly prohibited.
5. **Provider Abstraction Layer**:
   - LLMs, TTS engines, and Embedding models must adhere to abstract base classes (ABCs) defined in `app/core/providers/`:
     - `BaseLLMProvider` (methods: `generate_structured`, `generate_chat`)
     - `BaseTTSProvider` (methods: `synthesize_line`, `get_supported_voices`)
     - `BaseEmbeddingProvider` (methods: `embed_text`, `embed_batch`)
   - Domain logic must depend only on these abstractions, never on SDKs directly (e.g. `google-genai` or `groq`).

### 2.2 LangGraph Orchestration Standards
1. **Typed State Machine**:
   - Graph state must be defined as an explicit `TypedDict` or Pydantic model (`KathaEpisodeState`).
   - Reducers must be used for append-only lists (e.g. `revisions: Annotated[list[ScriptRevision], operator.add]`).
2. **Strict Loop Invariants**:
   - Every cycle must have an explicit counter and an invariant condition that guarantees termination:
     ```python
     def should_revise(state: KathaEpisodeState) -> str:
         if state["critic_score"] >= PASSING_SCORE or state["revision_count"] >= MAX_REVISIONS:
             return "localize"
         return "revise"
     ```
   - Maximum revisions must be strictly capped at 2.
3. **Observability Callback Hooks**:
   - All nodes must attach lifecycle listeners that report start, completion, latency, and token consumption to Langfuse and Redis SSE.

### 2.3 Audio Engineering & FFmpeg Rules
1. **Deterministic Audio Cache**:
   - Every audio line filename is generated as:
     `audio_cache/{sha256(text + voice_id + str(speed) + str(pitch) + provider_id)}.mp3`
   - Before dispatching a TTS request, check if the cache file exists. If it exists and is valid, return the cached path immediately.
2. **Audio Normalization**:
   - All concatenated audio tracks must pass through an FFmpeg filter chain implementing loudness normalization:
     `loudnorm=I=-16:TP=-1.5:LRA=11` (podcasting/audiobook loudness standard).
3. **Pacing & Micro-Pauses**:
   - Inter-dialogue pauses must be configurable (default 250ms silence between speaker transitions).
   - Scene transitions must inject a distinct acoustic pause (e.g., 800ms silence or transition sound effect).

### 2.4 Frontend (React 18 / Vite / TypeScript / Tailwind)
1. **Strict TypeScript**:
   - Enable `strict: true` in `tsconfig.json`. No `any` types.
   - API schemas must be shared or synchronized with backend Pydantic models.
2. **SSE Stream Handling**:
   - Wrap `EventSource` in a resilient custom hook (`useEpisodeStream`) featuring automatic reconnection, exponential backoff, and state reconciliation.
3. **State Management**:
   - Separate server state (React Query / TanStack Query) from transient UI state (Zustand).
4. **Accessible Audio UI**:
   - Waveform visualization using Wavesurfer.js with accessible controls (play/pause, seek, per-line highlight during playback).

---

## 3. Testing & Quality Assurance Rigor

### 3.1 Test Hierarchy
1. **Unit Tests (`tests/unit/`)**:
   - Test individual agent prompt formatters, schema validators, FFmpeg command builders, and utility functions in total isolation.
   - Target coverage: > 85%.
2. **Integration Tests (`tests/integration/`)**:
   - Test DB repositories with an in-memory/test PostgreSQL instance.
   - Test LangGraph workflow with **Mock Providers** (`MockLLMProvider`, `MockTTSProvider`) to ensure graph transitions, cycle termination, and error handling work predictably without invoking paid APIs.
3. **Audio Sanity Tests (`tests/audio/`)**:
   - Verify that generated MP3 files have non-zero duration, correct sampling rate (24kHz / 44.1kHz), and valid header information.
4. **Evaluation Benchmarks (`tests/eval/`)**:
   - Run golden dataset evaluation against LLM judges and track score drift across PRs.

### 3.2 Mocking & CI Safety
- Live external API keys (`GEMINI_API_KEY`, `GROQ_API_KEY`, `ELEVENLABS_API_KEY`) must **NEVER** be required to run the automated CI test suite.
- All provider tests must run against robust mock fixtures that simulate both successful responses and edge-case network/API errors (429 Rate Limits, 503 Overloaded, Malformed JSON).

---

## 4. Git & Contribution Workflow

1. **Conventional Commits**:
   - `feat(pipeline): add localizer agent for Hindi/Hinglish`
   - `fix(audio): handle ffmpeg crossfade clipping on short lines`
   - `test(critic): add unit tests for revision score thresholds`
   - `refactor(db): migrate story bible to pgvector HNSW index`
2. **Pull Request Checklist**:
   - [ ] Linters passed (`ruff check .`, `black --check .`, `npm run lint`).
   - [ ] Type checkers passed (`mypy app`, `tsc --noEmit`).
   - [ ] Unit & integration tests pass (`pytest tests/`).
   - [ ] No hardcoded credentials or API tokens.
   - [ ] Pydantic models updated and validated.
   - [ ] No unhandled exceptions or empty `except` blocks.

