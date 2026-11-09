from collections.abc import AsyncGenerator
from typing import Any
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.api.deps import get_db, get_llm_provider
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.base import Base
from app.models.user import User
from app.providers.base import BaseLLMProvider
from app.providers.mock import MockLLMProvider

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestAsyncSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest.fixture(autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Create all tables before each test and drop them after."""
    from app.services.story_bible import story_bible_service

    story_bible_service.session_factory = TestAsyncSessionLocal
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    story_bible_service.session_factory = None


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated test database session."""
    async with TestAsyncSessionLocal() as session:
        yield session


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    mock_llm_provider: MockLLMProvider,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX async test client with overridden database and LLM dependencies."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def override_get_llm_provider() -> BaseLLMProvider:
        return mock_llm_provider

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = override_get_llm_provider

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a default test user."""
    user = User(
        email="author@katha.studio",
        hashed_password=hash_password("StrongPassword123!"),
        full_name="Katha Creator",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Provide authorization headers for the default test user."""
    token = create_access_token(subject=test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    """Create a secondary test user for authorization boundary testing."""
    user = User(
        email="competitor@other.com",
        hashed_password=hash_password("OtherPassword123!"),
        full_name="Other Creator",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def other_auth_headers(other_user: User) -> dict[str, str]:
    """Provide authorization headers for the secondary test user."""
    token = create_access_token(subject=other_user.id)
    return {"Authorization": f"Bearer {token}"}

