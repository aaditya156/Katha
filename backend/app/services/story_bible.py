import logging
import math
from typing import Any
from sqlalchemy import or_, select
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
    """Production service for Story Bible episodic persistence, hybrid vector+keyword retrieval, and reranking."""

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

    async def hybrid_search(
        self,
        series_id: str,
        query: str,
        limit: int = 5,
        alpha: float = 0.6,
        retrieval_enabled: bool | None = None,
        db: AsyncSession | None = None,
    ) -> StoryBibleSearchResponse:
        """Perform hybrid vector + keyword retrieval with Reciprocal Rank Fusion (RRF) and reranking.

        Reliability Requirements:
        - Never silently treats retrieval failure as empty results.
        - Explicitly distinguishes RETRIEVAL_DISABLED vs RETRIEVAL_EMPTY vs RETRIEVAL_SUCCESS.
        """
        # 1. Check feature flag (ablation)
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
            # 2. Query Embedding
            try:
                query_vector = await self.embedding_provider.embed_text(query)
            except Exception as exc:
                raise StoryBibleRetrievalError("Embedding service failed during query encoding.", str(exc)) from exc

            # 3. Fetch candidates for this series only (Series Isolation)
            query_stmt = select(StoryBibleEntry).where(StoryBibleEntry.series_id == series_id)
            all_entries = (await db.scalars(query_stmt)).all()

            if not all_entries:
                return StoryBibleSearchResponse(
                    status="RETRIEVAL_EMPTY",
                    query=query,
                    results=[],
                    retrieval_enabled=True,
                )

            # 4. Dense Vector Scoring
            dense_scored: list[tuple[StoryBibleEntry, float]] = []
            for entry in all_entries:
                if entry.embedding:
                    sim = cosine_similarity(query_vector, entry.embedding)
                    dense_scored.append((entry, sim))
            dense_scored.sort(key=lambda x: x[1], reverse=True)

            # 5. Sparse Keyword Scoring
            query_tokens = set(query.lower().split())
            sparse_scored: list[tuple[StoryBibleEntry, float]] = []
            for entry in all_entries:
                entry_text = f"{entry.entity_name} {entry.content}".lower()
                matches = sum(1 for token in query_tokens if token in entry_text)
                score = matches / max(1, len(query_tokens))
                sparse_scored.append((entry, score))
            sparse_scored.sort(key=lambda x: x[1], reverse=True)

            # 6. Reciprocal Rank Fusion (RRF)
            rrf_scores: dict[str, float] = {}
            k_rrf = 60.0

            for rank, (entry, _) in enumerate(dense_scored):
                rrf_scores[entry.id] = rrf_scores.get(entry.id, 0.0) + (alpha * (1.0 / (k_rrf + rank + 1)))

            for rank, (entry, _) in enumerate(sparse_scored):
                rrf_scores[entry.id] = rrf_scores.get(entry.id, 0.0) + ((1.0 - alpha) * (1.0 / (k_rrf + rank + 1)))

            # Map entries
            entry_map = {e.id: e for e in all_entries}

            # 7. Reranking Service: Boost characters and open plot threads for audio continuity
            ranked_candidates = []
            for entry_id, score in rrf_scores.items():
                entry = entry_map[entry_id]
                # Continuity boost
                multiplier = 1.0
                if entry.entity_type == "character":
                    multiplier = 1.2
                elif entry.entity_type == "open_plot_thread":
                    multiplier = 1.25

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
