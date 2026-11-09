from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details representation for structured API errors."""

    model_config = ConfigDict(strict=True, frozen=True)

    type: str = Field(default="about:blank", description="URI reference identifying problem type")
    title: str = Field(..., description="Short, human-readable summary of problem")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Human-readable explanation specific to occurrence")
    error_code: str = Field(..., description="Application specific machine-readable error code")
    extras: dict[str, Any] = Field(default_factory=dict, description="Diagnostic contextual metadata")
