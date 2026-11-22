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
from app.services.story_bible import (
    CONTINUITY_WEIGHT_CHARACTER,
    CONTINUITY_WEIGHT_HIGH_IMPORTANCE,
    CONTINUITY_WEIGHT_LOW_IMPORTANCE,
    CONTINUITY_WEIGHT_PLOT_THREAD,
    CONTINUITY_WEIGHT_RULE,
    DEFAULT_RRF_K,
    StoryBibleService,
    calculate_continuity_multiplier,
    tokenize_multilingual_query,
)

settings = get_settings()

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg_session():
    """Provides an isolated AsyncSession against the live PostgreSQL database with pgvector."""
    if settings.DATABASE_URL.startswith("sqlite"):
        pytest.skip("PostgreSQL with pgvector is not configured (current DB is SQLite).")

    engine = create_async_engine(settings.DATABASE_URL)
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
    """Creates a deterministic test dataset in PostgreSQL for Series A (multilingual) and Series B."""
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

    # Add a world rule
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

    # Seed a Hindi Devanagari entry to test native multilingual FTS
    hindi_entry = StoryBibleEntry(
        series_id=series_a_id,
        episode_id=ep_a1_id,
        entity_type="location",
        entity_name="पुरानी हवेली",
        content="चांदनी चौक की पुरानी हवेली जहाँ 1947 के गुप्त दस्तावेज़ दबे हैं।",
        metadata_json={"importance": "high"},
        embedding=await service.embedding_provider.embed_text(
            "चांदनी चौक की पुरानी हवेली जहाँ 1947 के गुप्त दस्तावेज़ दबे हैं।"
        ),
    )
    pg_session.add(hindi_entry)

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
    """Verify native PostgreSQL pgvector cosine similarity search retrieves semantic matches."""
    series_a_id, _, service = seeded_series

    search_res = await service.hybrid_search(
        series_id=series_a_id,
        query="cynical smoker insomniac baritone radio broadcaster",
        limit=3,
        alpha=1.0,
        db=pg_session,
    )

    assert search_res.status == "RETRIEVAL_SUCCESS"
    assert len(search_res.results) > 0
    top_entity = search_res.results[0].entry
    assert top_entity.entity_name == "RJ Kabir"
    assert search_res.results[0].score > 0.0


async def test_postgres_multilingual_fts_english_hinglish_hindi(pg_session: AsyncSession, seeded_series):
    """Verify multilingual full-text search supports English, Hinglish, and Hindi Devanagari."""
    series_a_id, _, service = seeded_series

    # 1. English keyword test
    eng_res = await service.hybrid_search(
        series_id=series_a_id,
        query="partition property deeds underground vault",
        limit=3,
        alpha=0.0,
        db=pg_session,
    )
    assert eng_res.status == "RETRIEVAL_SUCCESS"
    assert any("Haveli Basement" in r.entry.entity_name for r in eng_res.results)

    # 2. Hinglish keyword test: unstemmed match for "haveli" and "thumri"
    hinglish_res = await service.hybrid_search(
        series_id=series_a_id,
        query="thumri singer haveli ruins",
        limit=3,
        alpha=0.0,
        db=pg_session,
    )
    assert hinglish_res.status == "RETRIEVAL_SUCCESS"
    assert any("Sultana Begum" in r.entry.entity_name for r in hinglish_res.results)

    # 3. Hindi (Devanagari) keyword test
    hindi_res = await service.hybrid_search(
        series_id=series_a_id,
        query="चांदनी चौक की पुरानी हवेली गुप्त दस्तावेज़",
        limit=3,
        alpha=0.0,
        db=pg_session,
    )
    assert hindi_res.status == "RETRIEVAL_SUCCESS"
    assert any("पुरानी हवेली" in r.entry.entity_name for r in hindi_res.results)


async def test_postgres_hybrid_retrieval_and_rrf_ranking(pg_session: AsyncSession, seeded_series):
    """Verify RRF correctly fuses dense vector and sparse keyword rankings."""
    series_a_id, _, service = seeded_series

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


async def test_postgres_mathematical_rrf_duplicate_handling(pg_session: AsyncSession, seeded_series):
    """Verify mathematical RRF formula: an item in both lists gets contributions from both dense and sparse."""
    series_a_id, _, service = seeded_series
    query = "lost partition property deeds hidden in Haveli basement"

    query_vec = await service.embedding_provider.embed_text(query)
    dense_scored, sparse_scored = await service._search_postgres(
        db=pg_session,
        series_id=series_a_id,
        query=query,
        query_vector=query_vec,
        candidate_limit=15,
    )

    # Find an entry appearing in both dense and sparse lists
    dense_map = {entry.id: rank for rank, (entry, _) in enumerate(dense_scored)}
    sparse_map = {entry.id: rank for rank, (entry, _) in enumerate(sparse_scored)}
    common_ids = set(dense_map.keys()) & set(sparse_map.keys())

    assert len(common_ids) > 0, "Expected at least one entity in both candidate sets."
    common_id = next(iter(common_ids))
    r_dense = dense_map[common_id]
    r_sparse = sparse_map[common_id]

    alpha = 0.60
    k_rrf = DEFAULT_RRF_K
    expected_dense_contrib = alpha * (1.0 / (k_rrf + r_dense + 1))
    expected_sparse_contrib = (1.0 - alpha) * (1.0 / (k_rrf + r_sparse + 1))
    expected_fused_rrf = expected_dense_contrib + expected_sparse_contrib

    # Run hybrid search and verify combined score reflects both contributions
    hybrid_res = await service.hybrid_search(
        series_id=series_a_id,
        query=query,
        limit=5,
        alpha=alpha,
        db=pg_session,
    )
    assert hybrid_res.status == "RETRIEVAL_SUCCESS"
    target_result = next((r for r in hybrid_res.results if r.entry.id == common_id), None)
    assert target_result is not None

    multiplier = calculate_continuity_multiplier(
        target_result.entry.entity_type,
        target_result.entry.metadata_json,
    )
    expected_final_score = min(1.0, expected_fused_rrf * 50.0 * multiplier)
    assert pytest.approx(target_result.score, abs=0.01) == round(expected_final_score, 3)


async def test_postgres_alpha_boundary_conditions(pg_session: AsyncSession, seeded_series):
    """Verify behavior at alpha = 0.0 (pure keyword) and alpha = 1.0 (pure semantic)."""
    series_a_id, _, service = seeded_series
    query = "lost partition property deeds hidden in Haveli basement"

    # alpha = 0.0: pure keyword
    res_alpha_0 = await service.hybrid_search(series_id=series_a_id, query=query, alpha=0.0, db=pg_session)
    assert res_alpha_0.status == "RETRIEVAL_SUCCESS"

    # alpha = 1.0: pure vector
    res_alpha_1 = await service.hybrid_search(series_id=series_a_id, query=query, alpha=1.0, db=pg_session)
    assert res_alpha_1.status == "RETRIEVAL_SUCCESS"


async def test_postgres_series_isolation(pg_session: AsyncSession, seeded_series):
    """Verify strict tenant/series isolation in PostgreSQL: Series B cannot retrieve Series A memories."""
    series_a_id, series_b_id, service = seeded_series

    search_res = await service.hybrid_search(
        series_id=series_b_id,
        query="RJ Kabir Sultana 1947 Haveli basement",
        limit=5,
        db=pg_session,
    )

    for r in search_res.results:
        assert r.entry.series_id == series_b_id
        assert r.entry.series_id != series_a_id
        assert r.entry.entity_name not in ("RJ Kabir", "Sultana Begum", "Haveli Basement")


async def test_postgres_deterministic_empty_retrieval(pg_session: AsyncSession, seeded_series):
    """Verify deterministic empty retrieval: queries with no semantic or keyword overlap return RETRIEVAL_EMPTY."""
    series_a_id, _, service = seeded_series

    search_res = await service.hybrid_search(
        series_id=series_a_id,
        query="xyzquantum9999 warp9999 unobtainium8888",
        limit=5,
        alpha=0.0,  # Pure sparse search on nonexistent words
        db=pg_session,
    )

    assert search_res.status == "RETRIEVAL_EMPTY"
    assert len(search_res.results) == 0


async def test_postgres_writer_prompt_context_injection(pg_session: AsyncSession, seeded_series):
    """Verify that retrieved Story Bible lore is ACTUALLY injected into the Writer agent's prompt."""
    from app.agents.graph import create_katha_graph
    from app.agents.state import KathaEpisodeState
    from app.providers.mock import MockLLMProvider
    from langgraph.checkpoint.memory import MemorySaver

    series_a_id, _, service = seeded_series

    captured_prompts: list[str] = []

    class PromptCapturingMockLLM(MockLLMProvider):
        async def generate_structured(self, prompt: str, schema, system_prompt: str = ""):
            captured_prompts.append(prompt)
            return await super().generate_structured(prompt, schema, system_prompt)

    llm = PromptCapturingMockLLM()
    graph = create_katha_graph(llm, checkpointer=MemorySaver())

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

        config = {"configurable": {"thread_id": f"thread_rag_prompt_{int(time.time()*1000)}"}}
        result = await graph.ainvoke(initial_state, config=config)

        assert result["status"] == "COMPLETED"

        # Verify that Writer prompt received the lore context header
        writer_prompts = [p for p in captured_prompts if "Relevant Story Bible Memories & Character Lore" in p]
        assert len(writer_prompts) > 0, "Writer prompt MUST include injected Story Bible context."
        assert "RJ Kabir" in writer_prompts[0] or "Haveli Basement" in writer_prompts[0]
    finally:
        story_bible_service.session_factory = orig_session_factory


async def test_unicode_aware_query_tokenization():
    """Verify Unicode-aware tokenizer preserves Devanagari graphemes and handles Hindi & English punctuation."""
    # 1. Hindi with danda, double danda, quotes and exclamation
    hindi_q = 'चांदनी चौक की पुरानी हवेली! क्या 1947 के "दस्तावेज़" सच हैं? हाँ, बिल्कुल।'
    hindi_tokens = tokenize_multilingual_query(hindi_q)
    assert "चांदनी" in hindi_tokens
    assert "हवेली" in hindi_tokens
    assert "दस्तावेज़" in hindi_tokens
    assert "बिल्कुल" in hindi_tokens
    assert "।" not in hindi_tokens
    assert "!" not in hindi_tokens
    assert '"' not in hindi_tokens

    # 2. Hinglish with hyphen, apostrophe, and mix of English/Hindi words
    hinglish_q = "RJ Kabir's late-night haveli broadcast... bhoot aaya kya?"
    hinglish_tokens = tokenize_multilingual_query(hinglish_q)
    assert "Kabir" in hinglish_tokens
    assert "haveli" in hinglish_tokens
    assert "broadcast" in hinglish_tokens
    assert "bhoot" in hinglish_tokens

    # 3. English formal legal query
    eng_q = "Secret safe: containing partition property deeds (1947)?"
    eng_tokens = tokenize_multilingual_query(eng_q)
    assert "deeds" in eng_tokens
    assert "1947" in eng_tokens
    assert "partition" in eng_tokens


async def test_populated_dataset_explain_analyze(pg_session: AsyncSession, seeded_series):
    """Verify actual query plans using EXPLAIN (ANALYZE, BUFFERS) on a populated, analyzed table."""
    series_a_id, _, service = seeded_series

    # 1. Populate 40 additional entries in Series A and Series B for realistic planner statistics
    for i in range(25):
        entry = StoryBibleEntry(
            series_id=series_a_id,
            entity_type="lore",
            entity_name=f"Haveli Room {i}",
            content=f"Secret room number {i} in old Delhi haveli with partition deeds and antiques.",
            metadata_json={"importance": "medium"},
            embedding=await service.embedding_provider.embed_text(f"Secret room {i} in haveli"),
        )
        pg_session.add(entry)
    await pg_session.commit()

    # 2. Run ANALYZE on the populated table to ensure up-to-date planner statistics
    await pg_session.execute(text("ANALYZE story_bible_entries"))

    # 3. Test Plan A: Production Multilingual Full-Text Search
    plan_fts_res = await pg_session.execute(
        text(
            f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT id, entity_name, ts_rank_cd(search_vector, (websearch_to_tsquery('english', 'haveli') || websearch_to_tsquery('simple', 'haveli'))) AS rank
            FROM story_bible_entries
            WHERE series_id = '{series_a_id}'
              AND search_vector @@ (websearch_to_tsquery('english', 'haveli') || websearch_to_tsquery('simple', 'haveli'))
            ORDER BY rank DESC
            LIMIT 10;
            """
        )
    )
    plan_fts = [row[0] for row in plan_fts_res.all()]
    print("\n--- [EXPLAIN ANALYZE: FTS] ---")
    for l in plan_fts:
        print(l)
    assert any("story_bible_entries" in l for l in plan_fts)

    # 4. Test Plan B: Production Vector Search with series_id filter
    query_vec = await service.embedding_provider.embed_text("secret room haveli deeds")
    vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

    plan_vec_res = await pg_session.execute(
        text(
            f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT id, entity_name, embedding <=> '{vec_str}'::vector AS distance
            FROM story_bible_entries
            WHERE series_id = '{series_a_id}'
              AND embedding IS NOT NULL
            ORDER BY embedding <=> '{vec_str}'::vector ASC
            LIMIT 10;
            """
        )
    )
    plan_vec = [row[0] for row in plan_vec_res.all()]
    print("\n--- [EXPLAIN ANALYZE: Vector Filtered] ---")
    for l in plan_vec:
        print(l)
    assert any("story_bible_entries" in l for l in plan_vec)

    # 5. Test Plan C: Unfiltered Global Vector Search (HNSW Index)
    await pg_session.execute(text("SET enable_seqscan = off"))
    try:
        plan_hnsw_res = await pg_session.execute(
            text(
                f"""
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT id, entity_name, embedding <=> '{vec_str}'::vector AS distance
                FROM story_bible_entries
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> '{vec_str}'::vector ASC
                LIMIT 10;
                """
            )
        )
        plan_hnsw = [row[0] for row in plan_hnsw_res.all()]
        print("\n--- [EXPLAIN ANALYZE: Unfiltered HNSW] ---")
        for l in plan_hnsw:
            print(l)
        assert any("idx_story_bible_embedding_hnsw" in l for l in plan_hnsw)
    finally:
        await pg_session.execute(text("SET enable_seqscan = on"))


async def test_continuity_weight_heuristics():
    """Verify that heuristic continuity multipliers behave predictably across entity types and metadata."""
    assert calculate_continuity_multiplier("character") == CONTINUITY_WEIGHT_CHARACTER
    assert calculate_continuity_multiplier("open_plot_thread") == CONTINUITY_WEIGHT_PLOT_THREAD
    assert calculate_continuity_multiplier("rule") == CONTINUITY_WEIGHT_RULE
    assert calculate_continuity_multiplier("location") == 1.0

    # High importance boost
    high_char = calculate_continuity_multiplier("character", {"importance": "critical"})
    assert pytest.approx(high_char, abs=1e-4) == CONTINUITY_WEIGHT_CHARACTER * CONTINUITY_WEIGHT_HIGH_IMPORTANCE

    # Low importance de-weight
    low_char = calculate_continuity_multiplier("character", {"importance": "low"})
    assert pytest.approx(low_char, abs=1e-4) == CONTINUITY_WEIGHT_CHARACTER * CONTINUITY_WEIGHT_LOW_IMPORTANCE
