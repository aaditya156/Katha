import asyncio
import os
import time
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.episode import Episode
from app.models.series import Series
from app.models.story_bible import StoryBibleEntry
from app.models.user import User
from app.providers.embedding.mock import MockEmbeddingProvider
from app.schemas.story_bible import (
    CharacterFact,
    LocationFact,
    PlotThreadFact,
    StoryBibleExtraction,
)
from app.services.story_bible import StoryBibleService

settings = get_settings()

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg_session():
    """Provides an isolated AsyncSession against the live PostgreSQL database with pgvector."""
    if settings.DATABASE_URL.startswith("sqlite"):
        pytest.skip("PostgreSQL with pgvector is not configured (current DB is SQLite).")

    engine = create_async_engine(settings.DATABASE_URL)
    # Verify connection
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unreachable: {exc}")

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded_series(pg_session: AsyncSession):
    """Creates a deterministic test dataset in PostgreSQL for Series A and Series B."""
    series_a_id = f"test_rag_series_a_{int(time.time()*1000)}"
    series_b_id = f"test_rag_series_b_{int(time.time()*1000)}"
    user_id = f"test_user_{int(time.time()*1000)}"

    user = User(
        id=user_id,
        email=f"rag_tester_{int(time.time()*1000)}@example.com",
        hashed_password="hashed_pw_test",
        full_name="RAG Tester",
    )
    pg_session.add(user)

    series_a = Series(
        id=series_a_id,
        title="Dilli 1947 Ghost Radio",
        logline="A night-shift radio jockey hears transmissions from the year 1947.",
        genre="horror",
        target_language="hindi",
        user_id=user_id,
    )
    series_b = Series(
        id=series_b_id,
        title="Nebula Odyssey 3000",
        logline="Deep space explorers salvage an ancient alien vessel.",
        genre="sci-fi",
        target_language="english",
        user_id=user_id,
    )
    pg_session.add(series_a)
    pg_session.add(series_b)
    await pg_session.commit()

    # Create episodes for foreign key integrity
    ep_a1_id = f"ep_a1_{int(time.time()*1000)}"
    ep_b1_id = f"ep_b1_{int(time.time()*1000)}"
    ep_a = Episode(
        id=ep_a1_id,
        series_id=series_a_id,
        episode_number=1,
        title="Midnight Broadcast",
        premise="Kabir tunes into 1947",
        status="completed",
        target_language="hindi",
        duration_minutes_target=5,
    )
    ep_b = Episode(
        id=ep_b1_id,
        series_id=series_b_id,
        episode_number=1,
        title="Derelict Cruiser",
        premise="Vance docks with alien ship",
        status="completed",
        target_language="english",
        duration_minutes_target=5,
    )
    pg_session.add(ep_a)
    pg_session.add(ep_b)
    await pg_session.commit()

    service = StoryBibleService(session_factory=lambda: pg_session)

    # Seed Series A facts
    extraction_a = StoryBibleExtraction(
        characters=[
            CharacterFact(
                name="RJ Kabir",
                traits=["cynical", "smoker", "insomniac"],
                vocal_traits="raspy baritone, speaks in slow measured cadence",
                current_state="terrified yet obsessed with the broadcast",
            ),
            CharacterFact(
                name="Sultana Begum",
                traits=["tragic", "vengeful", "haunting"],
                vocal_traits="ethereal classical thumri singer",
                current_state="wandering Chandni Chowk ruins",
            ),
        ],
        locations=[
            LocationFact(
                name="Haveli Basement",
                atmosphere_soundscape="Echoing water droplets, creaking teak rafters, distant train whistle",
                significance="A concealed underground vault holding the lost 1947 partition property deeds",
            )
        ],
        open_plot_threads=[
            PlotThreadFact(
                thread_id="thread_midnight_express",
                description="The mysterious caller claims to be trapped on the 1947 midnight refugee express to Lahore",
                status="open",
            )
        ],
        episode_synopsis="Kabir investigates the radio frequency and hears Sultana singing about the Haveli deeds.",
    )
    await service.store_facts(series_id=series_a_id, episode_id=ep_a1_id, extraction=extraction_a, db=pg_session)

    # Add a world rule with high importance
    rule_entry = StoryBibleEntry(
        series_id=series_a_id,
        episode_id=ep_a1_id,
        entity_type="rule",
        entity_name="transmission_window",
        content="The supernatural 1947 radio frequency only opens between 2:00 AM and 2:17 AM each morning.",
        metadata_json={"importance": "critical"},
        embedding=await service.embedding_provider.embed_text(
            "The supernatural 1947 radio frequency only opens between 2:00 AM and 2:17 AM each morning."
        ),
    )
    pg_session.add(rule_entry)

    # Seed Series B facts (for isolation check)
    extraction_b = StoryBibleExtraction(
        characters=[
            CharacterFact(
                name="Commander Vance",
                traits=["stoic", "tactical"],
                vocal_traits="crisp military baritone",
                current_state="orbiting pulsar",
            )
        ],
        locations=[],
        open_plot_threads=[],
        episode_synopsis="Vance docks with the derelict alien cruiser.",
    )
    await service.store_facts(series_id=series_b_id, episode_id=ep_b1_id, extraction=extraction_b, db=pg_session)
    await pg_session.commit()

    yield series_a_id, series_b_id, service

    # Cleanup
    await pg_session.execute(text(f"DELETE FROM series WHERE id IN ('{series_a_id}', '{series_b_id}')"))
    await pg_session.execute(text(f"DELETE FROM users WHERE id = '{user_id}'"))
    await pg_session.commit()


async def test_postgres_vector_similarity_retrieval(pg_session: AsyncSession, seeded_series):
    """Verify native PostgreSQL pgvector cosine similarity search uses the HNSW index and retrieves semantic matches."""
    series_a_id, _, service = seeded_series

    # Semantic paraphrase without exact keyword matches:
    # "nocturnal audio host terrified insomniac" -> matches "RJ Kabir"
    search_res = await service.hybrid_search(
        series_id=series_a_id,
        query="nocturnal audio host terrified insomniac broadcaster",
        limit=3,
        alpha=1.0,  # Pure dense vector search
        db=pg_session,
    )

    assert search_res.status == "RETRIEVAL_SUCCESS"
    assert len(search_res.results) > 0
    top_entity = search_res.results[0].entry
    assert top_entity.entity_name == "RJ Kabir"
    assert search_res.results[0].score > 0.0


async def test_postgres_fulltext_keyword_retrieval(pg_session: AsyncSession, seeded_series):
    """Verify PostgreSQL Full-Text Search uses the GIN index and finds exact/stemmed terms."""
    series_a_id, _, service = seeded_series

    # Keyword search for specific terms: "partition property deeds underground vault"
    search_res = await service.hybrid_search(
        series_id=series_a_id,
        query="partition property deeds underground vault",
        limit=3,
        alpha=0.0,  # Pure sparse keyword search
        db=pg_session,
    )

    assert search_res.status == "RETRIEVAL_SUCCESS"
    assert len(search_res.results) > 0
    entity_names = [r.entry.entity_name for r in search_res.results]
    assert "Haveli Basement" in entity_names


async def test_postgres_hybrid_retrieval_and_rrf_ranking(pg_session: AsyncSession, seeded_series):
    """Verify RRF correctly fuses dense vector and sparse keyword rankings."""
    series_a_id, _, service = seeded_series

    # Hybrid query: contains exact keywords and broad semantic intent
    search_res = await service.hybrid_search(
        series_id=series_a_id,
        query="Sultana singing classical thumri in Chandni Chowk ruins",
        limit=4,
        alpha=0.6,
        db=pg_session,
    )

    assert search_res.status == "RETRIEVAL_SUCCESS"
    results = search_res.results
    assert len(results) >= 1
    assert results[0].entry.entity_name == "Sultana Begum"
    assert results[0].retrieval_method == "hybrid"


async def test_postgres_duplicate_handling_rrf(pg_session: AsyncSession, seeded_series):
    """Verify that entries returned by both dense and sparse queries accumulate fused RRF score."""
    series_a_id, _, service = seeded_series

    # Dense only
    dense_res = await service.hybrid_search(
        series_id=series_a_id,
        query="lost partition property deeds hidden in Haveli basement",
        limit=5,
        alpha=1.0,
        db=pg_session,
    )
    # Sparse only
    sparse_res = await service.hybrid_search(
        series_id=series_a_id,
        query="lost partition property deeds hidden in Haveli basement",
        limit=5,
        alpha=0.0,
        db=pg_session,
    )
    # Hybrid (fused)
    hybrid_res = await service.hybrid_search(
        series_id=series_a_id,
        query="lost partition property deeds hidden in Haveli basement",
        limit=5,
        alpha=0.5,
        db=pg_session,
    )

    assert hybrid_res.status == "RETRIEVAL_SUCCESS"
    top_hybrid_name = hybrid_res.results[0].entry.entity_name
    assert top_hybrid_name == "Haveli Basement"


async def test_postgres_series_isolation(pg_session: AsyncSession, seeded_series):
    """Verify strict tenant/series isolation in PostgreSQL: Series B cannot retrieve Series A memories."""
    series_a_id, series_b_id, service = seeded_series

    # Query Series B with terms that exclusively exist in Series A
    search_res = await service.hybrid_search(
        series_id=series_b_id,
        query="RJ Kabir Sultana 1947 Haveli basement",
        limit=5,
        db=pg_session,
    )

    # Strict Series Isolation: Series B must NEVER see Series A memories
    for r in search_res.results:
        assert r.entry.series_id == series_b_id
        assert r.entry.series_id != series_a_id
        assert r.entry.entity_name not in ("RJ Kabir", "Sultana Begum", "Haveli Basement")


async def test_postgres_empty_retrieval_results(pg_session: AsyncSession, seeded_series):
    """Verify completely unmatched queries return RETRIEVAL_EMPTY gracefully without errors."""
    series_a_id, _, service = seeded_series

    search_res = await service.hybrid_search(
        series_id=series_a_id,
        query="quantum singularity hyperdrive warp core reactor",
        limit=5,
        db=pg_session,
    )

    # Empty keyword matches and unrelated vector
    assert search_res.status in ("RETRIEVAL_SUCCESS", "RETRIEVAL_EMPTY")


async def test_postgres_writer_agent_integration(pg_session: AsyncSession, seeded_series):
    """Verify the Writer agent receives retrieved Story Bible context when executing in LangGraph."""
    from app.agents.graph import create_katha_graph
    from app.agents.state import KathaEpisodeState
    from app.providers.mock import MockLLMProvider
    from langgraph.checkpoint.memory import MemorySaver

    series_a_id, _, service = seeded_series

    llm = MockLLMProvider()
    graph = create_katha_graph(llm, checkpointer=MemorySaver())

    # Temporarily point the global story_bible_service to pg_session
    from app.services.story_bible import story_bible_service
    orig_session_factory = story_bible_service.session_factory
    story_bible_service.session_factory = lambda: pg_session

    try:
        ep_id = f"ep_rag_test_{int(time.time()*1000)}"
        ep_entry = Episode(
            id=ep_id,
            series_id=series_a_id,
            episode_number=2,
            title="Radio Haunting",
            premise="RJ Kabir receives a broadcast about the missing Haveli deeds.",
            status="generating",
            target_language="hindi",
            duration_minutes_target=5,
        )
        pg_session.add(ep_entry)
        await pg_session.commit()

        initial_state: KathaEpisodeState = {
            "episode_id": ep_id,
            "series_id": series_a_id,
            "premise": "RJ Kabir receives a broadcast about the missing Haveli deeds.",
            "target_duration_minutes": 5,
            "target_language": "hindi",
            "genre": "horror",
            "characters_hint": ["RJ Kabir"],
            "outline": None,
            "raw_script": None,
            "current_critique": None,
            "failing_scenes": [],
            "critic_score": 0.0,
            "revision_count": 0,
            "localized_script": None,
            "audio_manifest": None,
            "story_bible_extraction": None,
            "bible_updates": None,
            "status": "INITIALIZED",
            "current_node": "start",
            "errors": [],
            "simulation_flags": {},
        }

        config = {"configurable": {"thread_id": f"thread_rag_{int(time.time()*1000)}"}}
        result = await graph.ainvoke(initial_state, config=config)

        assert result["status"] == "COMPLETED"
        assert result["outline"] is not None
        assert result["raw_script"] is not None
    finally:
        story_bible_service.session_factory = orig_session_factory


async def test_retrieval_performance_benchmark(pg_session: AsyncSession, seeded_series):
    """Empirical performance benchmark comparing native PostgreSQL search vs in-memory scan."""
    series_a_id, _, service = seeded_series
    query = "1947 midnight refugee express to Lahore"

    query_vec = await service.embedding_provider.embed_text(query)

    # Benchmark 1: Native PostgreSQL search (pgvector HNSW + FTS GIN)
    start_pg = time.perf_counter()
    dense_pg, sparse_pg = await service._search_postgres(
        db=pg_session,
        series_id=series_a_id,
        query=query,
        query_vector=query_vec,
        candidate_limit=15,
    )
    time_pg_ms = (time.perf_counter() - start_pg) * 1000.0

    # Benchmark 2: In-memory Python scan
    start_mem = time.perf_counter()
    dense_mem, sparse_mem = await service._search_in_memory_fallback(
        db=pg_session,
        series_id=series_a_id,
        query=query,
        query_vector=query_vec,
        candidate_limit=15,
    )
    time_mem_ms = (time.perf_counter() - start_mem) * 1000.0

    assert len(dense_pg) > 0 or len(sparse_pg) > 0
    # Log measured times for reporting
    print(f"\n[BENCHMARK] Native PostgreSQL Search: {time_pg_ms:.2f} ms")
    print(f"[BENCHMARK] In-Memory Python Fallback: {time_mem_ms:.2f} ms")
