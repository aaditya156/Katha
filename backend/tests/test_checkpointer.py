import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.agents.checkpointer import get_checkpointer, get_in_memory_checkpointer


@pytest.mark.asyncio
async def test_in_memory_checkpointer() -> None:
    saver = get_in_memory_checkpointer()
    assert isinstance(saver, BaseCheckpointSaver)


@pytest.mark.asyncio
async def test_postgres_checkpointer_interface_and_fallback() -> None:
    # When sqlite or force_memory is set, cleanly returns in-memory saver
    saver = await get_checkpointer(force_memory=True)
    assert isinstance(saver, BaseCheckpointSaver)

    # Verify AsyncPostgresSaver class attributes and methods exist
    assert hasattr(AsyncPostgresSaver, "from_conn_string")
    assert hasattr(AsyncPostgresSaver, "setup")
