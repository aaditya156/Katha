# Katha Studio: Key Engineering Decisions & Architectural Tradeoffs

> **Architectural Decision Records (ADRs) and Design Rationale**

---

## 1. LangGraph for Orchestration (vs Linear Chains or Autonomous Agents)

### Context:
Audio drama generation is not a one-shot prompt task. It requires planning, drafting, critical revision, language localization, and voice casting. Autonomous agent frameworks (like AutoGen or CrewAI) often suffer from non-deterministic looping, unconstrained token burn, and unpredictable termination.

### Decision:
We implemented **LangGraph** with a strictly typed state machine (`KathaEpisodeState`) and bounded conditional revision loop.

### Tradeoff Analysis:
- **Pros**:
  - **Deterministic Termination Invariant**: The graph strictly caps revisions at $N \le 2$. Infinite loops are mathematically impossible.
  - **State Checkpointing**: Using `PostgresSaver`, any crash mid-generation preserves the state graph in PostgreSQL, enabling zero-loss resumption.
  - **Selective Scene Rewriting**: The Critic identifies exact failing scene indices, allowing the Writer to rewrite only flawed scenes rather than regenerating the entire script.
- **Cons**:
  - Higher initial implementation overhead compared to basic LangChain chains.

---

## 2. PostgreSQL + pgvector (vs Standalone Vector DB like Pinecone/Qdrant)

### Context:
Katha Studio stores structured entities (Users, Series, Episodes, Cast Scripts) alongside unstructured narrative memory (Story Bible facts, character lore, relational dynamics).

### Decision:
We standardized on **PostgreSQL 16 with the pgvector extension** for unified relational and vector storage.

### Tradeoff Analysis:
- **Pros**:
  - **Transactional Consistency (ACID)**: Story Bible facts and episode status updates commit inside single atomic transactions (`async with session.begin()`).
  - **Zero Data Sync Drift**: Eliminates the synchronization lag and dual-write failure modes inherent in syncing Postgres with an external vector DB.
  - **Native Hybrid Search**: We execute vector cosine similarity and full-text keyword search in the same database engine, fused via Reciprocal Rank Fusion (RRF).
  - **Operational Simplicity**: Single backup (`pg_dump`), single replication topology, and zero third-party cloud vector billing.
- **Cons**:
  - Slightly lower indexing throughput at billion-vector scale compared to specialized distributed engines (irrelevant for series story bibles).

---

## 3. Server-Sent Events (SSE) vs WebSockets

### Context:
The agentic pipeline takes 15–45 seconds to generate an audio episode. The frontend requires real-time progress indicators (which agent node is currently executing, token counts, and intermediate critique scores).

### Decision:
We chose **Server-Sent Events (SSE)** over bidirectional WebSockets for pipeline streaming.

### Tradeoff Analysis:
- **Pros**:
  - **Unidirectional Match**: Story generation progress flows strictly server-to-client; bidirectional client messaging is unnecessary during execution.
  - **HTTP/2 & Proxy Compatibility**: Works natively over standard HTTP/2 multiplexing, simplifying Nginx configuration (`proxy_buffering off;`).
  - **Automatic Reconnection**: Native browser `EventSource` handles connection dropouts with automatic retry backoff.
- **Cons**:
  - Text-only framing (JSON payloads), though well-suited for status events.

---

## 4. Deterministic SHA-256 Audio Caching

### Context:
Commercial TTS providers (ElevenLabs, Sarvam) charge per character and incur 1–3s latency per line. In an interactive studio, users frequently regenerate 1 or 2 lines while leaving the remaining 40 lines untouched.

### Decision:
Every dialogue line generates a deterministic cache key:
$$\text{Key} = \text{SHA256}(\text{normalized\_text} + \text{voice\_id} + \text{speed} + \text{pitch} + \text{provider})$$

### Tradeoff Analysis:
- **Pros**:
  - **Sub-Second Master Re-assembly**: Regenerating a single line only calls TTS for that line; the remaining lines load instantly from disk, saving $> 90\%$ of TTS credits and latency.
  - **Idempotent Synthesis**: Duplicate synthesis requests yield zero redundant API spend.
- **Cons**:
  - Disk storage footprint for MP3 files (managed via cache retention policies).

---

## 5. Provider Abstraction Layer (ABCs)

### Context:
Rapid model evolution requires the ability to switch between Gemini, Groq, Claude, ElevenLabs, and Sarvam without touching core business logic.

### Decision:
We enforced abstract base classes (`BaseLLMProvider`, `BaseTTSProvider`, `BaseEmbeddingProvider`) in `app/core/providers/`. Application code depends exclusively on these interfaces.

### Tradeoff Analysis:
- **Pros**:
  - **Hermetic CI Testing**: Tests run against `MockLLMProvider` and `MockTTSProvider`, ensuring automated tests never fail due to external rate limits or require paid API tokens.
  - **Vendor Independence**: Adding a new Indian-language TTS provider (e.g., Bhashini) requires writing a single adapter class.

