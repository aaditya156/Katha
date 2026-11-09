from functools import lru_cache
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Katha Studio"
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str = Field(
        default="replace-this-with-a-secure-random-secret-key-in-production-min32chars",
        description="JWT encryption secret key",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://katha:katha_secret@localhost:5432/katha_studio",
        description="Async database connection string",
    )
    DATABASE_ECHO: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM Providers
    LLM_DEFAULT_PROVIDER: Literal["mock", "gemini", "groq"] = "mock"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 2

    # Audio & TTS
    TTS_DEFAULT_PROVIDER: Literal["mock", "sarvam", "elevenlabs"] = "mock"
    SARVAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""

    # Observability
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        # Normalize sqlite to aiosqlite for async tests if needed
        if v.startswith("sqlite:///") and not v.startswith("sqlite+aiosqlite:///"):
            return v.replace("sqlite:///", "sqlite+aiosqlite:///")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

