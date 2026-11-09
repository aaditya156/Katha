import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from app.models.base import Base
# Ensure all models are imported
import app.models # noqa: F401


@pytest.mark.asyncio
async def test_database_schema_definitions() -> None:
    """Validate that all models generate expected table and column definitions."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def inspect_tables(connection):
            inspector = inspect(connection)
            tables = inspector.get_table_names()
            return tables

        tables = await conn.run_sync(inspect_tables)
        assert "users" in tables
        assert "series" in tables
        assert "episodes" in tables

    await engine.dispose()

