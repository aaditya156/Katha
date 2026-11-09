from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import (
    AuthenticationFailedException,
    DuplicateEntityException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.api.deps import get_current_active_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Register a new user account with hashed password and return JWT tokens."""
    # Check duplicate email
    existing_user = await db.scalar(select(User).where(User.email == data.email))
    if existing_user:
        raise DuplicateEntityException("User", "email", data.email)

    hashed_pw = hash_password(data.password)
    user = User(
        email=data.email,
        hashed_password=hashed_pw,
        full_name=data.full_name,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate with email and password, returning JWT access and refresh tokens."""
    user = await db.scalar(select(User).where(User.email == data.email))
    if not user or not verify_password(data.password, user.hashed_password):
        raise AuthenticationFailedException(detail="Invalid email or password.")

    if not user.is_active:
        raise AuthenticationFailedException(detail="Account is inactive.")

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse.model_validate(current_user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    refresh_token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Exchange a valid refresh token for a new access and refresh token pair."""
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthenticationFailedException(detail="Token is not a valid refresh token.")

    user_id = payload.get("sub")
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user or not user.is_active:
        raise AuthenticationFailedException(detail="User no longer exists or is inactive.")

    new_access_token = create_access_token(subject=user.id)
    new_refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        user=UserResponse.model_validate(user),
    )

