import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from app.agents.checkpointer import (
    close_postgres_checkpointer,
    get_checkpointer,
    get_in_memory_checkpointer,
    init_checkpointer,
)
from app.agents.graph import create_katha_graph
from app.agents.state import KathaEpisodeState
from app.core.config import get_settings
from app.main import app, lifespan
from app.providers.mock import MockLLMProvider

settings = get_settings()


class TrackingMockLLM(MockLLMProvider):
    """Deterministic Mock LLM that tracks exact invocation counts per Pydantic schema."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.call_counts = {
            "EpisodeOutline": 0,
            "Script": 0,
            "CritiqueReport": 0,
            "LocalizedScript": 0,
            "CastScript": 0,
            "StoryBibleExtraction": 0,
        }

    async def generate_structured(self, prompt, schema, system_prompt=None):
        name = schema.__name__
        if name in self.call_counts:
            self.call_counts[name] += 1
        return await super().generate_structured(prompt, schema, system_prompt)


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
    
    Verifies:
    1. Planner and Writer execute in Context 1 before simulated failure at Critic.
    2. Connection pool 1 is closed completely.
    3. Fresh checkpointer and connection pool 2 are initialized in Context 2.
    4. The same thread ID is used for recovery.
    5. Previously completed Planner and Writer nodes are NOT re-executed in Context 2.
    6. Critic, Localizer, VoiceCaster, and BibleUpdater execute to completion.
    7. Final workflow status is COMPLETED.
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

    llm_1 = TrackingMockLLM()
    graph_1 = create_katha_graph(llm=llm_1, checkpointer=saver_1)

    # Execution fails at Critic node as simulated
    with pytest.raises(RuntimeError) as exc_info:
        await graph_1.ainvoke(initial_state, config=config)
    assert "Simulated forced failure at Critic node" in str(exc_info.value)

    # Verify Planner and Writer executed in Context 1
    assert llm_1.call_counts["EpisodeOutline"] == 1, "Planner should have run in Context 1"
    assert llm_1.call_counts["Script"] == 1, "Writer should have run in Context 1"
    assert llm_1.call_counts["CritiqueReport"] == 0, "Critic should have failed before LLM generation"

    # Close Context 1 completely (destroying connection pool and graph)
    await pool_1.close()

    # --- Execution Context 2 (Completely Fresh Connection Pool & Checkpointer) ---
    pool_2 = AsyncConnectionPool(
        conninfo=pg_url,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    await pool_2.open()
    saver_2 = AsyncPostgresSaver(conn=pool_2)

    # 1. Verify that checkpoint was persisted in PostgreSQL and contains Planner & Writer artifacts
    checkpoint_state = await saver_2.aget(config)
    assert checkpoint_state is not None, "Checkpoint must exist in PostgreSQL"
    saved_values = checkpoint_state.get("channel_values", {})
    assert saved_values.get("outline") is not None, "Outline must be preserved in PostgreSQL"
    assert saved_values.get("raw_script") is not None, "Raw script must be preserved in PostgreSQL"
    assert saved_values["outline"].title != ""
    assert len(saved_values["raw_script"].scenes) >= 1

    # 2. Reinitialize graph with a fresh TrackingMockLLM and clear the failure flag via aupdate_state
    llm_2 = TrackingMockLLM()
    graph_2 = create_katha_graph(llm=llm_2, checkpointer=saver_2)
    await graph_2.aupdate_state(config, {"simulation_flags": {}})

    # 3. Resume execution from the checkpoint on the same thread_id (passing None to resume from checkpoint)
    resumed_result = await graph_2.ainvoke(None, config=config)

    # 4. VERIFY DETERMINISTICALLY: Planner and Writer were NOT re-executed in Context 2
    assert llm_2.call_counts["EpisodeOutline"] == 0, (
        "Planner was unnecessarily re-executed during checkpoint recovery!"
    )
    assert llm_2.call_counts["Script"] == 0, (
        "Writer was unnecessarily re-executed during checkpoint recovery!"
    )
    assert llm_2.call_counts["CritiqueReport"] == 1, "Critic should execute upon resume"
    assert llm_2.call_counts["LocalizedScript"] == 1, "Localizer should execute upon resume"
    assert llm_2.call_counts["CastScript"] == 1, "Voice Caster should execute upon resume"
    assert llm_2.call_counts["StoryBibleExtraction"] == 1, "Bible Updater should execute upon resume"

    # 5. Assert graph recovered and completed successfully
    assert resumed_result["status"] == "COMPLETED"
    assert resumed_result["localized_script"] is not None
    assert resumed_result["cast_script"] is not None
    assert resumed_result["bible_updates"] is not None

    await pool_2.close()


# --- Fast, Deterministic Unit Tests for Checkpointer Lifecycle ---

@pytest.mark.asyncio
async def test_lifespan_postgres_checkpointer_initialization_and_shutdown() -> None:
    """Verify that PostgreSQL checkpointer is initialized on startup and closed on shutdown."""
    with patch("app.agents.checkpointer.init_checkpointer", new_callable=AsyncMock) as mock_init, \
         patch("app.agents.checkpointer.close_postgres_checkpointer", new_callable=AsyncMock) as mock_close, \
         patch("app.core.events.event_hub.initialize", new_callable=AsyncMock), \
         patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://katha:secret@db:5432/test"):
        async with lifespan(app):
            mock_init.assert_awaited_once()
        mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_sqlite_uses_in_memory_checkpointer() -> None:
    """Verify that SQLite environments do not initialize PostgreSQL connection pools."""
    mock_conn = AsyncMock()
    mock_conn.run_sync = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn
    mock_engine.begin.return_value.__aexit__.return_value = None

    with patch("app.agents.checkpointer.init_checkpointer", new_callable=AsyncMock) as mock_init, \
         patch("app.agents.checkpointer.close_postgres_checkpointer", new_callable=AsyncMock) as mock_close, \
         patch("app.core.events.event_hub.initialize", new_callable=AsyncMock), \
         patch("app.core.database.engine", mock_engine), \
         patch.object(settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:"):
        async with lifespan(app):
            mock_init.assert_not_called()
        mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_checkpointer_sqlite_returns_memory_saver() -> None:
    """Verify that init_checkpointer returns MemorySaver when SQLite is configured."""
    with patch.object(settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:"):
        saver = await init_checkpointer()
        assert isinstance(saver, MemorySaver)


@pytest.mark.asyncio
async def test_postgres_initialization_failure_raises_explicit_runtime_error() -> None:
    """Verify that PostgreSQL initialization failure is NOT silently hidden by an in-memory fallback."""
    with patch("psycopg_pool.AsyncConnectionPool.open", side_effect=Exception("Database unreachable")), \
         patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://katha:secret@db:5432/test"), \
         patch("app.agents.checkpointer._postgres_saver", None):
        with pytest.raises(RuntimeError) as exc_info:
            await init_checkpointer()
        assert "Failed to initialize durable PostgreSQL checkpointer" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_checkpointer_never_silently_falls_back_on_postgres_failure() -> None:
    """Verify get_checkpointer raises RuntimeError if PostgreSQL connection fails in production."""
    with patch("psycopg_pool.AsyncConnectionPool.open", side_effect=Exception("Database unreachable")), \
         patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://katha:secret@db:5432/test"), \
         patch("app.agents.checkpointer._postgres_saver", None):
        with pytest.raises(RuntimeError) as exc_info:
            await get_checkpointer(force_memory=False)
        assert "Failed to initialize durable PostgreSQL checkpointer" in str(exc_info.value)
