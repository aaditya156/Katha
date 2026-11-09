import pytest
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.graph import create_katha_graph
from app.agents.state import KathaEpisodeState
from app.models.series import Series
from app.models.story_bible import StoryBibleEntry
from app.models.user import User
from app.providers.embedding.mock import MockEmbeddingProvider
from app.providers.mock import MockLLMProvider
from app.schemas.story_bible import (
    CharacterFact,
    LocationFact,
    PlotThreadFact,
    RelationshipFact,
    StoryBibleEntryCreate,
    StoryBibleExtraction,
)
from app.services.story_bible import StoryBibleRetrievalError, cosine_similarity, story_bible_service


@pytest.mark.asyncio
async def test_mock_embedding_provider_cosine_similarity() -> None:
    """Verify embedding provider generates normalized 768-dim vectors with accurate cosine similarity."""
    embedder = MockEmbeddingProvider(dimension=768)

    v1 = await embedder.embed_text("RJ Kabir receives a broadcast from 1947")
    v2 = await embedder.embed_text("RJ Kabir receives a broadcast from 1947")
    v3 = await embedder.embed_text("Late night radio DJ Kabir gets 1947 telegram")
    v4 = await embedder.embed_text("Delicious mango kulfi recipe with pistachios")

    # Dimensions
    assert len(v1) == 768
    # Exact match similarity must be 1.0
    sim_exact = cosine_similarity(v1, v2)
    assert pytest.approx(sim_exact, abs=1e-4) == 1.0

    # Semantically related text (overlapping words) should have high similarity
    sim_related = cosine_similarity(v1, v3)
    assert sim_related > 0.2

    # Completely unrelated text should have lower similarity than related
    sim_unrelated = cosine_similarity(v1, v4)
    assert sim_related > sim_unrelated


@pytest.mark.asyncio
async def test_store_facts_and_deduplication(db_session: AsyncSession) -> None:
    """Verify storing facts deduplicates characters and merges traits instead of creating redundant rows."""
    series_id = "test_series_dedup_1"

    # Episode 1 extraction
    ep1_facts = StoryBibleExtraction(
        characters=[
            CharacterFact(
                name="Kabir",
                traits=["skeptical", "curious"],
                vocal_traits="baritone",
                current_state="intrigued",
            )
        ],
        locations=[
            LocationFact(
                name="Radio Mirage",
                atmosphere_soundscape="Low AC hum",
                significance="Late night studio",
            )
        ],
        open_plot_threads=[
            PlotThreadFact(
                thread_id="thread_1947_caller",
                description="Caller claim about 1947 train",
                status="open",
            )
        ],
        episode_synopsis="Kabir takes a strange call.",
    )

    await story_bible_service.store_facts(
        series_id=series_id,
        episode_id="ep_1",
        extraction=ep1_facts,
        db=db_session,
    )

    # Check that character Kabir was created
    kabir_entries = (
        await db_session.scalars(
            select(StoryBibleEntry).where(
                StoryBibleEntry.series_id == series_id,
                StoryBibleEntry.entity_type == "character",
                StoryBibleEntry.entity_name == "Kabir",
            )
        )
    ).all()
    assert len(kabir_entries) == 1
    assert set(kabir_entries[0].metadata_json["traits"]) == {"skeptical", "curious"}

    # Episode 2 extraction with new developments for Kabir
    ep2_facts = StoryBibleExtraction(
        characters=[
            CharacterFact(
                name="Kabir",
                traits=["dread", "obsessive"],
                vocal_traits="baritone",
                current_state="paranoid",
            )
        ],
        locations=[],
        open_plot_threads=[],
        episode_synopsis="Kabir finds a 1947 telegram.",
    )

    await story_bible_service.store_facts(
        series_id=series_id,
        episode_id="ep_2",
        extraction=ep2_facts,
        db=db_session,
    )

    # Verify Kabir was NOT duplicated, but updated with merged traits
    kabir_updated = (
        await db_session.scalars(
            select(StoryBibleEntry).where(
                StoryBibleEntry.series_id == series_id,
                StoryBibleEntry.entity_type == "character",
                StoryBibleEntry.entity_name == "Kabir",
            )
        )
    ).all()
    assert len(kabir_updated) == 1
    # Traits merged
    expected_traits = {"skeptical", "curious", "dread", "obsessive"}
    assert set(kabir_updated[0].metadata_json["traits"]) == expected_traits
    assert "paranoid" in kabir_updated[0].content


@pytest.mark.asyncio
async def test_hybrid_retrieval_dense_sparse_rrf(db_session: AsyncSession) -> None:
    """Verify dense vector + sparse keyword search combined via RRF retrieves relevant lore."""
    series_id = "test_series_rrf_1"

    facts = StoryBibleExtraction(
        characters=[
            CharacterFact(
                name="Devraj",
                traits=["ruthless", "aristocrat"],
                vocal_traits="deep commanding",
                current_state="scheming",
            ),
            CharacterFact(
                name="Meera",
                traits=["rebellious", "artist"],
                vocal_traits="soft whisper",
                current_state="in hiding",
            ),
        ],
        locations=[
            LocationFact(
                name="Haveli Basement",
                atmosphere_soundscape="Dripping water, creaking wooden beams",
                significance="Secret safe with 1947 property deeds",
            )
        ],
        open_plot_threads=[
            PlotThreadFact(
                thread_id="missing_deeds",
                description="Where are the 1947 partition property deeds hidden?",
                status="open",
            )
        ],
        episode_synopsis="Meera infiltrates the Haveli basement searching for the 1947 property deeds.",
    )

    await story_bible_service.store_facts(
        series_id=series_id,
        episode_id="ep_1",
        extraction=facts,
        db=db_session,
    )

    # Search for deeds in haveli
    search_res = await story_bible_service.hybrid_search(
        series_id=series_id,
        query="property deeds 1947 in haveli basement",
        limit=3,
        db=db_session,
    )

    assert search_res.status == "RETRIEVAL_SUCCESS"
    assert len(search_res.results) > 0
    top_entity_names = [r.entry.entity_name for r in search_res.results]
    assert "Haveli Basement" in top_entity_names or "missing_deeds" in top_entity_names
    assert search_res.results[0].score > 0.0
    assert search_res.results[0].retrieval_method == "hybrid"


@pytest.mark.asyncio
async def test_series_isolation(db_session: AsyncSession) -> None:
    """Enforce strict series isolation: Series B cannot retrieve Series A memories."""
    series_a = "series_a_confidential"
    series_b = "series_b_empty"

    facts = StoryBibleExtraction(
        characters=[
            CharacterFact(
                name="SecretAgent_X",
                traits=["classified"],
                vocal_traits="monotone",
                current_state="active",
            )
        ],
        locations=[],
        open_plot_threads=[],
        episode_synopsis="Top secret mission in Berlin.",
    )

    await story_bible_service.store_facts(
        series_id=series_a,
        episode_id="ep_1",
        extraction=facts,
        db=db_session,
    )

    # Query from Series B
    search_b = await story_bible_service.hybrid_search(
        series_id=series_b,
        query="SecretAgent_X Berlin",
        limit=5,
        db=db_session,
    )

    assert search_b.status == "RETRIEVAL_EMPTY"
    assert len(search_b.results) == 0


@pytest.mark.asyncio
async def test_retrieval_ablation_flag(db_session: AsyncSession) -> None:
    """Verify STORY_BIBLE_RETRIEVAL_ENABLED=False returns RETRIEVAL_DISABLED and bypasses DB querying."""
    series_id = "test_series_ablation"

    search_res = await story_bible_service.hybrid_search(
        series_id=series_id,
        query="any query",
        retrieval_enabled=False,
        db=db_session,
    )

    assert search_res.status == "RETRIEVAL_DISABLED"
    assert search_res.retrieval_enabled is False
    assert len(search_res.results) == 0


@pytest.mark.asyncio
async def test_retrieval_failure_never_swallowed(db_session: AsyncSession) -> None:
    """AGENTS.md No-Silent-Failure: Vector/embedding failures must raise explicit exception, not return empty."""
    from app.services.story_bible import StoryBibleService

    class BrokenEmbeddingProvider(MockEmbeddingProvider):
        async def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("Upstream Embedding API 500 Connection Refused")

    broken_service = StoryBibleService(embedding_provider=BrokenEmbeddingProvider())

    with pytest.raises(StoryBibleRetrievalError) as exc_info:
        await broken_service.hybrid_search(
            series_id="test_series_err",
            query="test query",
            db=db_session,
        )

    assert "Story Bible retrieval failed" in str(exc_info.value)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_multi_episode_continuity(db_session: AsyncSession) -> None:
    """Verify Episode 1 generates and saves Story Bible; Episode 2 Planner and Writer retrieve lore for continuity."""
    series_id = "series_continuity_test_100"

    llm = MockLLMProvider()
    checkpointer = MemorySaver()
    graph = create_katha_graph(llm=llm, checkpointer=checkpointer)

    # 1. Run Episode 1
    ep1_state: KathaEpisodeState = {
        "series_id": series_id,
        "episode_id": "ep_1",
        "episode_number": 1,
        "premise": "RJ Kabir takes a spooky 1947 call on Radio Mirage.",
        "target_language": "hinglish",
        "target_duration_minutes": 5,
        "genre": "thriller",
        "characters_hint": ["Kabir", "Ananya"],
        "revision_count": 0,
        "critique_history": [],
        "errors": [],
        "failing_scenes": [],
        "status": "INITIALIZED",
        "current_node": "start",
        "simulation_flags": {},
    }

    final_ep1 = await graph.ainvoke(ep1_state, config={"configurable": {"thread_id": "thread_ep1"}})
    assert final_ep1["status"] == "COMPLETED"
    assert final_ep1["story_bible_extraction"] is not None

    # Check facts exist in DB for series_id
    saved = (await db_session.scalars(select(StoryBibleEntry).where(StoryBibleEntry.series_id == series_id))).all()
    assert len(saved) >= 1

    # 2. Run Episode 2: Planner & Writer should query and find Episode 1 memories
    ep2_state: KathaEpisodeState = {
        "series_id": series_id,
        "episode_id": "ep_2",
        "episode_number": 2,
        "premise": "Kabir investigates the address from the 1947 telegram in Old Delhi.",
        "target_language": "hinglish",
        "target_duration_minutes": 5,
        "genre": "thriller",
        "characters_hint": ["Kabir"],
        "revision_count": 0,
        "critique_history": [],
        "errors": [],
        "failing_scenes": [],
        "status": "INITIALIZED",
        "current_node": "start",
        "simulation_flags": {},
    }

    final_ep2 = await graph.ainvoke(ep2_state, config={"configurable": {"thread_id": "thread_ep2"}})
    assert final_ep2["status"] == "COMPLETED"
    assert final_ep2["outline"] is not None
    assert final_ep2["raw_script"] is not None


@pytest.mark.asyncio
async def test_story_bible_api_crud_and_search(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify REST API for Story Bible: list, create, search, delete, and cross-user authorization enforcement."""
    # 1. Create a Series
    series = Series(
        title="Dilli Ke Bhoot",
        logline="Ghost stories of Old Delhi",
        genre="horror",
        target_language="hindi",
        user_id=test_user.id,
    )
    db_session.add(series)
    await db_session.commit()
    await db_session.refresh(series)
    series_id = series.id

    # 2. Add an entry via POST
    entry_payload = {
        "entity_type": "character",
        "entity_name": "Sultana",
        "content": "A courtesan whose ghost sings in Chandni Chowk ruins.",
        "metadata_json": {"vocal_style": "classical thumri"},
    }
    create_resp = await client.post(
        f"/api/v1/series/{series_id}/bible",
        json=entry_payload,
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["entity_name"] == "Sultana"
    entry_id = created_data["id"]

    # 3. List entries via GET
    list_resp = await client.get(
        f"/api/v1/series/{series_id}/bible",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 4. Search entries via POST /search
    search_resp = await client.post(
        f"/api/v1/series/{series_id}/bible/search",
        json={"query": "ghost singing courtesan in chandni chowk", "limit": 3},
        headers=auth_headers,
    )
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["status"] == "RETRIEVAL_SUCCESS"
    assert len(search_data["results"]) == 1
    assert search_data["results"][0]["entry"]["entity_name"] == "Sultana"

    # 5. Authorization Boundary: other_user cannot access series_id Story Bible
    unauth_resp = await client.get(
        f"/api/v1/series/{series_id}/bible",
        headers=other_auth_headers,
    )
    assert unauth_resp.status_code == 403

    # 6. Delete entry via DELETE
    del_resp = await client.delete(
        f"/api/v1/series/{series_id}/bible/{entry_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    # Verify deletion
    list_after = await client.get(
        f"/api/v1/series/{series_id}/bible",
        headers=auth_headers,
    )
    assert len(list_after.json()) == 0
