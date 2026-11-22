import logging
import math
import re
from typing import Any
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.exceptions import KathaException
from app.models.story_bible import StoryBibleEntry
from app.providers.embedding.base import BaseEmbeddingProvider
from app.providers.embedding.mock import MockEmbeddingProvider
from app.schemas.story_bible import (
    StoryBibleEntryResponse,
    StoryBibleExtraction,
    StoryBibleSearchResponse,
    StoryBibleSearchResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class StoryBibleRetrievalError(KathaException):
    """Raised when story bible retrieval fails unexpectedly."""

    def __init__(self, detail: str, original_error: str | None = None) -> None:
        super().__init__(
            detail=f"Story Bible retrieval failed: {detail}",
            status_code=502,
            title="Story Bible Retrieval Error",
            error_code="STORY_BIBLE_RETRIEVAL_ERROR",
            extras={"original_error": original_error},
        )


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two unit vectors (dot product)."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


class StoryBibleService:
    """Production service for Story Bible episodic persistence, native pgvector + full-text search, and RRF ranking."""

    def __init__(
        self,
        embedding_provider: BaseEmbeddingProvider | None = None,
        session_factory: Any = None,
    ) -> None:
        self.embedding_provider = embedding_provider or MockEmbeddingProvider()
        self.session_factory = session_factory

    def get_session(self) -> AsyncSession:
        if self.session_factory is not None:
            return self.session_factory()
        return async_session_factory()

    def is_retrieval_enabled(self, state_override: bool | None = None) -> bool:
        """Check if story bible retrieval is active (supports ablation flags)."""
        if state_override is not None:
            return state_override
        return settings.STORY_BIBLE_RETRIEVAL_ENABLED

    async def store_facts(
        self,
        series_id: str,
        episode_id: str,
        extraction: StoryBibleExtraction,
        db: AsyncSession | None = None,
    ) -> list[StoryBibleEntry]:
        """Deduplicate and store extracted episodic facts, computing embeddings for each entity."""
        should_close = False
        if db is None:
            session_cm = self.get_session()
            db = await session_cm.__aenter__()
            should_close = True

        saved_entries: list[StoryBibleEntry] = []
        try:
            # 1. Store or update characters (Deduplication)
            for char in extraction.characters:
                existing = await db.scalar(
                    select(StoryBibleEntry).where(
                        StoryBibleEntry.series_id == series_id,
                        StoryBibleEntry.entity_type == "character",
                        StoryBibleEntry.entity_name == char.name,
                    )
                )
                content = (
                    f"Character: {char.name}. "
                    f"Traits: {', '.join(char.traits)}. "
                    f"Voice Archetype: {char.vocal_traits}. "
                    f"State: {char.current_state}."
                )
                embedding = await self.embedding_provider.embed_text(content)

                if existing:
                    # Merge developments into existing character profile
                    existing.content = content
                    meta = dict(existing.metadata_json)
                    meta["traits"] = list(set(meta.get("traits", []) + char.traits))
                    meta["last_episode_seen"] = episode_id
                    existing.metadata_json = meta
                    existing.embedding = embedding
                    saved_entries.append(existing)
                else:
                    new_entry = StoryBibleEntry(
                        series_id=series_id,
                        episode_id=episode_id,
                        entity_type="character",
                        entity_name=char.name,
                        content=content,
                        metadata_json={
                            "traits": char.traits,
                            "vocal_traits": char.vocal_traits,
                            "first_episode_introduced": episode_id,
                        },
                        embedding=embedding,
                    )
                    db.add(new_entry)
                    saved_entries.append(new_entry)

            # 2. Store Open Plot Threads
            for thread in extraction.open_plot_threads:
                content = f"Open Plot Thread [{thread.thread_id}]: {thread.description} (Status: {thread.status})"
                embedding = await self.embedding_provider.embed_text(content)
                new_thread = StoryBibleEntry(
                    series_id=series_id,
                    episode_id=episode_id,
                    entity_type="open_plot_thread",
                    entity_name=thread.thread_id,
                    content=content,
                    metadata_json={"thread_id": thread.thread_id, "status": thread.status},
                    embedding=embedding,
                )
                db.add(new_thread)
                saved_entries.append(new_thread)

            # 3. Store Locations
            for loc in extraction.locations:
                content = f"Location: {loc.name}. Acoustic Soundscape: {loc.atmosphere_soundscape}. Significance: {loc.significance}."
                embedding = await self.embedding_provider.embed_text(content)
                new_loc = StoryBibleEntry(
                    series_id=series_id,
                    episode_id=episode_id,
                    entity_type="location",
                    entity_name=loc.name,
                    content=content,
                    metadata_json={"soundscape": loc.atmosphere_soundscape},
                    embedding=embedding,
                )
                db.add(new_loc)
                saved_entries.append(new_loc)

            # 4. Store Episodic Synopsis
            if extraction.episode_synopsis:
                synopsis_content = f"Episode Summary: {extraction.episode_synopsis}"
                syn_embed = await self.embedding_provider.embed_text(synopsis_content)
                syn_entry = StoryBibleEntry(
                    series_id=series_id,
                    episode_id=episode_id,
                    entity_type="episode_summary",
                    entity_name=f"Episode {episode_id}",
                    content=synopsis_content,
                    metadata_json={"synopsis": extraction.episode_synopsis},
                    embedding=syn_embed,
                )
                db.add(syn_entry)
                saved_entries.append(syn_entry)

            await db.commit()
            return saved_entries

        except Exception as exc:
            await db.rollback()
            logger.error(f"Failed to persist Story Bible facts: {exc}", exc_info=True)
            raise
        finally:
            if should_close:
                await db.close()

    async def _search_postgres(
        self,
        db: AsyncSession,
        series_id: str,
        query: str,
        query_vector: list[float],
        candidate_limit: int,
    ) -> tuple[list[tuple[StoryBibleEntry, float]], list[tuple[StoryBibleEntry, float]]]:
        """Execute native pgvector cosine similarity search and PostgreSQL full-text search directly in the database."""
        # 1. Native pgvector Cosine Similarity Search using HNSW index
        dist_expr = StoryBibleEntry.embedding.cosine_distance(query_vector).label("distance")
        dense_stmt = (
            select(
                StoryBibleEntry,
                dist_expr,
            )
            .where(
                StoryBibleEntry.series_id == series_id,
                StoryBibleEntry.embedding.is_not(None),
            )
            .order_by(dist_expr.asc())
            .limit(candidate_limit)
        )
        dense_rows = (await db.execute(dense_stmt)).all()
        # Filter out completely unrelated memories (cosine similarity < 0.1)
        dense_scored: list[tuple[StoryBibleEntry, float]] = []
        for row in dense_rows:
            sim = max(0.0, 1.0 - float(row[1]))
            if sim >= 0.1:
                dense_scored.append((row[0], sim))

        # 2. Native PostgreSQL Full-Text Search using GIN index
        tsv_expr = func.to_tsvector(
            "english",
            func.concat(
                func.coalesce(StoryBibleEntry.entity_name, ""),
                " ",
                func.coalesce(StoryBibleEntry.entity_type, ""),
                " ",
                func.coalesce(StoryBibleEntry.content, ""),
            ),
        )

        words = [w for w in re.findall(r"\w+", query) if len(w) > 1]
        if words:
            ts_query_str = " OR ".join(words)
        else:
            ts_query_str = query

        ts_query = func.websearch_to_tsquery("english", ts_query_str)
        rank_expr = func.ts_rank_cd(tsv_expr, ts_query).label("rank")

        sparse_stmt = (
            select(StoryBibleEntry, rank_expr)
            .where(
                StoryBibleEntry.series_id == series_id,
                tsv_expr.op("@@")(ts_query),
            )
            .order_by(rank_expr.desc())
            .limit(candidate_limit)
        )
        sparse_rows = (await db.execute(sparse_stmt)).all()
        sparse_scored: list[tuple[StoryBibleEntry, float]] = [
            (row[0], float(row[1])) for row in sparse_rows
        ]

        return dense_scored, sparse_scored

    async def _search_in_memory_fallback(
        self,
        db: AsyncSession,
        series_id: str,
        query: str,
        query_vector: list[float],
        candidate_limit: int,
    ) -> tuple[list[tuple[StoryBibleEntry, float]], list[tuple[StoryBibleEntry, float]]]:
        """Fallback candidate scoring for SQLite / non-PostgreSQL testing environments."""
        stmt = select(StoryBibleEntry).where(StoryBibleEntry.series_id == series_id)
        all_entries = (await db.scalars(stmt)).all()

        dense_scored: list[tuple[StoryBibleEntry, float]] = []
        for entry in all_entries:
            if entry.embedding:
                sim = cosine_similarity(query_vector, entry.embedding)
                if sim >= 0.1:
                    dense_scored.append((entry, sim))
        dense_scored.sort(key=lambda x: x[1], reverse=True)

        query_tokens = set(query.lower().split())
        sparse_scored: list[tuple[StoryBibleEntry, float]] = []
        for entry in all_entries:
            entry_text = f"{entry.entity_name} {entry.entity_type} {entry.content}".lower()
            matches = sum(1 for token in query_tokens if token in entry_text)
            if matches > 0:
                score = matches / max(1, len(query_tokens))
                sparse_scored.append((entry, score))
        sparse_scored.sort(key=lambda x: x[1], reverse=True)

        return dense_scored[:candidate_limit], sparse_scored[:candidate_limit]

    async def hybrid_search(
        self,
        series_id: str,
        query: str,
        limit: int = 5,
        alpha: float = 0.6,
        retrieval_enabled: bool | None = None,
        db: AsyncSession | None = None,
    ) -> StoryBibleSearchResponse:
        """Perform hybrid vector + keyword retrieval with Reciprocal Rank Fusion (RRF) and continuity reranking.

        Reliability Requirements:
        - Never silently treats retrieval failure as empty results.
        - Directly executes pgvector and PostgreSQL FTS inside the database when PostgreSQL is active.
        - Falls back gracefully to in-memory evaluation only on SQLite test setups.
        - Combines ranks via standard Reciprocal Rank Fusion (k=60).
        """
        if not self.is_retrieval_enabled(retrieval_enabled):
            logger.info(f"Story Bible retrieval disabled by feature flag for series '{series_id}'.")
            return StoryBibleSearchResponse(
                status="RETRIEVAL_DISABLED",
                query=query,
                results=[],
                retrieval_enabled=False,
            )

        should_close = False
        if db is None:
            session_cm = self.get_session()
            db = await session_cm.__aenter__()
            should_close = True

        try:
            # 1. Query Embedding
            try:
                query_vector = await self.embedding_provider.embed_text(query)
            except Exception as exc:
                raise StoryBibleRetrievalError("Embedding service failed during query encoding.", str(exc)) from exc

            # 2. Fetch candidate lists from DB using appropriate dialect engine
            candidate_limit = max(limit * 3, 15)
            is_postgres = False
            try:
                bind = db.get_bind()
                if bind is not None and getattr(bind.dialect, "name", "") == "postgresql":
                    is_postgres = True
            except Exception:
                if not str(settings.DATABASE_URL).startswith("sqlite"):
                    is_postgres = True

            if is_postgres:
                dense_scored, sparse_scored = await self._search_postgres(
                    db=db,
                    series_id=series_id,
                    query=query,
                    query_vector=query_vector,
                    candidate_limit=candidate_limit,
                )
            else:
                dense_scored, sparse_scored = await self._search_in_memory_fallback(
                    db=db,
                    series_id=series_id,
                    query=query,
                    query_vector=query_vector,
                    candidate_limit=candidate_limit,
                )

            if not dense_scored and not sparse_scored:
                return StoryBibleSearchResponse(
                    status="RETRIEVAL_EMPTY",
                    query=query,
                    results=[],
                    retrieval_enabled=True,
                )

            # 3. Reciprocal Rank Fusion (RRF) with standard k = 60
            rrf_scores: dict[str, float] = {}
            k_rrf = 60.0
            entry_map: dict[str, StoryBibleEntry] = {}

            for rank, (entry, _) in enumerate(dense_scored):
                entry_map[entry.id] = entry
                rrf_scores[entry.id] = rrf_scores.get(entry.id, 0.0) + (alpha * (1.0 / (k_rrf + rank + 1)))

            for rank, (entry, _) in enumerate(sparse_scored):
                entry_map[entry.id] = entry
                rrf_scores[entry.id] = rrf_scores.get(entry.id, 0.0) + ((1.0 - alpha) * (1.0 / (k_rrf + rank + 1)))

            # 4. Continuity & Entity Relevance Reranking
            ranked_candidates: list[tuple[StoryBibleEntry, float]] = []
            for entry_id, score in rrf_scores.items():
                entry = entry_map[entry_id]
                multiplier = 1.0

                # Type-based continuity weighting
                if entry.entity_type == "character":
                    multiplier = 1.2
                elif entry.entity_type == "open_plot_thread":
                    multiplier = 1.25
                elif entry.entity_type == "rule":
                    multiplier = 1.15

                # Metadata-based importance weighting if present
                meta = entry.metadata_json or {}
                imp = meta.get("importance")
                if imp in ("high", "critical", 5, 4):
                    multiplier *= 1.15
                elif imp in ("low", 1):
                    multiplier *= 0.9

                normalized_score = min(1.0, score * 50.0 * multiplier)
                ranked_candidates.append((entry, normalized_score))

            ranked_candidates.sort(key=lambda x: x[1], reverse=True)
            top_results = ranked_candidates[:limit]

            results = [
                StoryBibleSearchResult(
                    entry=StoryBibleEntryResponse.model_validate(item),
                    score=round(s, 3),
                    retrieval_method="hybrid",
                )
                for item, s in top_results
            ]

            return StoryBibleSearchResponse(
                status="RETRIEVAL_SUCCESS" if results else "RETRIEVAL_EMPTY",
                query=query,
                results=results,
                retrieval_enabled=True,
            )

        except Exception as exc:
            if isinstance(exc, StoryBibleRetrievalError):
                raise
            raise StoryBibleRetrievalError("Database query failed during memory retrieval.", str(exc)) from exc
        finally:
            if should_close:
                await db.close()


story_bible_service = StoryBibleService()


story_bible_service = StoryBibleService()
