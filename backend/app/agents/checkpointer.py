import logging
from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_in_memory_checkpointer = MemorySaver()

# Persistent PostgreSQL Checkpointer Pool Manager
_postgres_pool: Any = None
_postgres_saver: Any = None


def get_in_memory_checkpointer() -> BaseCheckpointSaver[Any]:
    """Return in-memory checkpointer for testing and lightweight sessions."""
    return _in_memory_checkpointer


async def init_checkpointer() -> BaseCheckpointSaver[Any]:
    """Initialize checkpointer during application startup based on DATABASE_URL.

    - SQLite: returns the global in-memory MemorySaver.
    - PostgreSQL: opens an AsyncConnectionPool, configures AsyncPostgresSaver,
      and verifies checkpoint tables via saver.setup().

    Raises:
        RuntimeError: If PostgreSQL is configured but checkpointer initialization fails.
    """
    global _postgres_pool, _postgres_saver

    if settings.DATABASE_URL.startswith("sqlite"):
        logger.info("Using MemorySaver checkpointer for SQLite.")
        return _in_memory_checkpointer

    if _postgres_saver is not None:
        return _postgres_saver

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        logger.info("Initializing persistent AsyncPostgresSaver connection pool...")
        pool = AsyncConnectionPool(
            conninfo=pg_url,
            max_size=10,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        await pool.open()

        saver = AsyncPostgresSaver(conn=pool)
        await saver.setup()

        _postgres_pool = pool
        _postgres_saver = saver
        logger.info("AsyncPostgresSaver initialized successfully with verified checkpoint tables.")
        return _postgres_saver

    except Exception as exc:
        # Never swallow failure in a production PostgreSQL environment
        logger.error(
            f"Fatal error initializing durable PostgreSQL checkpointer: {exc}",
            exc_info=True,
        )
        if pool is not None:
            try:
                await pool.close()
            except Exception:
                pass
        _postgres_pool = None
        _postgres_saver = None
        raise RuntimeError(
            f"Failed to initialize durable PostgreSQL checkpointer: {exc}"
        ) from exc


async def get_checkpointer(force_memory: bool = False) -> BaseCheckpointSaver[Any]:
    """Get checkpointer: AsyncPostgresSaver in production, MemorySaver as fallback or in tests.

    If PostgreSQL is configured and the checkpointer has not been initialized,
    attempts initialization. Never silently falls back to MemorySaver when
    PostgreSQL is configured.
    """
    if force_memory or settings.DATABASE_URL.startswith("sqlite"):
        return _in_memory_checkpointer

    if _postgres_saver is not None:
        return _postgres_saver

    return await init_checkpointer()


async def close_postgres_checkpointer() -> None:
    """Cleanly close persistent checkpointer connection pool during application shutdown."""
    global _postgres_pool, _postgres_saver
    if _postgres_pool is not None:
        try:
            await _postgres_pool.close()
            logger.info("AsyncPostgresSaver connection pool closed cleanly.")
        except Exception as exc:
            logger.warning(f"Error closing AsyncPostgresSaver pool: {exc}")
        finally:
            _postgres_pool = None
            _postgres_saver = None
