import os
import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from app.agents.checkpointer import get_checkpointer, get_in_memory_checkpointer
from app.agents.graph import create_katha_graph
from app.agents.state import KathaEpisodeState
from app.core.config import get_settings
from app.providers.mock import MockLLMProvider

settings = get_settings()


@pytest.mark.asyncio
async def test_in_memory_checkpointer() -> None:
    saver = get_in_memory_checkpointer()
    assert isinstance(saver, BaseCheckpointSaver)


@pytest.mark.asyncio
async def test_postgres_checkpointer_interface_and_fallback() -> None:
    # When force_memory is set, cleanly returns in-memory saver
    saver = await get_checkpointer(force_memory=True)
    assert isinstance(saver, BaseCheckpointSaver)

    # Verify AsyncPostgresSaver class attributes and methods exist
    assert hasattr(AsyncPostgresSaver, "from_conn_string")
    assert hasattr(AsyncPostgresSaver, "setup")


@pytest.mark.asyncio
async def test_postgres_checkpoint_persistence_and_recovery() -> None:
    """Validate true PostgreSQL checkpoint persistence across separate execution contexts.
    
    Demonstrates:
    1. Start a graph execution with AsyncPostgresSaver.
    2. Persist intermediate state during execution.
    3. Simulate mid-run failure at Critic node.
    4. Close the original execution context and connection pool completely.
    5. Reinitialize graph and a new checkpointer connection in a fresh context.
    6. Verify that previously completed nodes (Planner, Writer) are preserved in PostgreSQL.
    7. Resume execution using the same thread_id and verify it runs to COMPLETED.
    """
    pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    if not pg_url.startswith("postgresql://"):
        pytest.skip("PostgreSQL DATABASE_URL not configured for integration test.")

    thread_id = f"test_thread_recovery_{os.urandom(4).hex()}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: KathaEpisodeState = {
        "series_id": "series_pg_test_01",
        "episode_id": "ep_pg_test_01",
        "episode_number": 1,
        "premise": "A late-night broadcast echoes from an empty studio.",
        "target_language": "hinglish",
        "target_duration_minutes": 5,
        "genre": "supernatural",
        "characters_hint": ["Kabir"],
        "revision_count": 0,
        "critique_history": [],
        "errors": [],
        "failing_scenes": [],
        "status": "INITIALIZED",
        "current_node": "start",
        "simulation_flags": {"fail_at_node": "critic"},
    }

    # --- Execution Context 1 ---
    pool_1 = AsyncConnectionPool(
        conninfo=pg_url,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    await pool_1.open()
    saver_1 = AsyncPostgresSaver(conn=pool_1)
    await saver_1.setup()

    llm = MockLLMProvider()
    graph_1 = create_katha_graph(llm=llm, checkpointer=saver_1)

    # Execution fails at Critic node as simulated
    with pytest.raises(RuntimeError) as exc_info:
        await graph_1.ainvoke(initial_state, config=config)
    assert "Simulated forced failure at Critic node" in str(exc_info.value)

    # Close Context 1 completely (destroying connection pool and graph)
    await pool_1.close()

    # --- Execution Context 2 (Completely Fresh Connection) ---
    pool_2 = AsyncConnectionPool(
        conninfo=pg_url,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    await pool_2.open()
    saver_2 = AsyncPostgresSaver(conn=pool_2)

    # 1. Verify that checkpoint was persisted in PostgreSQL
    checkpoint_state = await saver_2.aget(config)
    assert checkpoint_state is not None
    saved_values = checkpoint_state.get("channel_values", {})
    assert saved_values.get("outline") is not None
    assert saved_values.get("raw_script") is not None
    assert saved_values["outline"].title != ""
    assert len(saved_values["raw_script"].scenes) >= 1

    # 2. Resume execution from the saved checkpoint on the same thread_id
    graph_2 = create_katha_graph(llm=llm, checkpointer=saver_2)
    resume_state: KathaEpisodeState = {"simulation_flags": {}}
    resumed_result = await graph_2.ainvoke(resume_state, config=config)

    # 3. Assert graph recovered and completed all downstream nodes
    assert resumed_result["status"] == "COMPLETED"
    assert resumed_result["localized_script"] is not None
    assert resumed_result["cast_script"] is not None
    assert resumed_result["bible_updates"] is not None

    await pool_2.close()
