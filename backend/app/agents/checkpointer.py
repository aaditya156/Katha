import logging
from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_in_memory_checkpointer = MemorySaver()


def get_in_memory_checkpointer() -> BaseCheckpointSaver[Any]:
    """Return in-memory checkpointer for testing and lightweight sessions."""
    return _in_memory_checkpointer


async def get_checkpointer(force_memory: bool = False) -> BaseCheckpointSaver[Any]:
    """Get checkpointer: AsyncPostgresSaver in production, MemorySaver as fallback or in tests."""
    if force_memory or settings.DATABASE_URL.startswith("sqlite"):
        return _in_memory_checkpointer

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # Convert asyncpg URL to standard psycopg URL for checkpointer
        pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        async with AsyncPostgresSaver.from_conn_string(pg_url) as saver:
            await saver.setup()
            return saver
    except Exception as exc:
        logger.warning(
            f"Could not initialize AsyncPostgresSaver ({exc}); using MemorySaver fallback."
        )
        return _in_memory_checkpointer

