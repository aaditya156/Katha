from typing import Annotated
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationFailedException
from app.core.security import decode_token
from app.models.user import User
from app.providers.base import BaseLLMProvider
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider
from app.providers.mock import MockLLMProvider

settings = get_settings()
security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate Bearer token and fetch authenticated user from database."""
    if not credentials:
        raise AuthenticationFailedException(detail="Authorization credentials were not provided.")

    token = credentials.credentials
    payload = decode_token(token)

    token_type = payload.get("type")
    if token_type != "access":
        raise AuthenticationFailedException(detail="Invalid token type for authorization.")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationFailedException(detail="Token payload is missing user identifier.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise AuthenticationFailedException(detail="User corresponding to this token does not exist.")

    if not user.is_active:
        raise AuthenticationFailedException(detail="User account is deactivated.")

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


def get_llm_provider() -> BaseLLMProvider:
    """Dependency that returns the configured LLM provider instance."""
    provider_name = settings.LLM_DEFAULT_PROVIDER.lower()
    if provider_name == "gemini":
        return GeminiProvider()
    elif provider_name == "groq":
        return GroqProvider()
    else:
        return MockLLMProvider()

