from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128, description="User password")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True, strict=True)

    id: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenPayload(BaseModel):
    sub: str
    iat: int
    exp: int
    type: str

