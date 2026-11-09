from typing import Any


class KathaException(Exception):
    """Base exception for Katha Studio domain errors conforming to RFC 7807."""

    def __init__(
        self,
        detail: str,
        status_code: int = 400,
        title: str = "Bad Request",
        error_code: str = "BAD_REQUEST",
        error_type: str = "about:blank",
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.title = title
        self.error_code = error_code
        self.error_type = error_type
        self.extras = extras or {}


class EntityNotFoundException(KathaException):
    def __init__(self, entity_name: str, identifier: Any) -> None:
        super().__init__(
            detail=f"{entity_name} with identifier '{identifier}' was not found.",
            status_code=404,
            title="Entity Not Found",
            error_code="ENTITY_NOT_FOUND",
        )


class DuplicateEntityException(KathaException):
    def __init__(self, entity_name: str, field: str, value: Any) -> None:
        super().__init__(
            detail=f"{entity_name} with {field} '{value}' already exists.",
            status_code=409,
            title="Duplicate Entity",
            error_code="DUPLICATE_ENTITY",
        )


class AuthenticationFailedException(KathaException):
    def __init__(self, detail: str = "Invalid credentials or expired token.") -> None:
        super().__init__(
            detail=detail,
            status_code=401,
            title="Authentication Failed",
            error_code="AUTHENTICATION_FAILED",
        )


class AuthorizationFailedException(KathaException):
    def __init__(self, detail: str = "You do not have permission to access this resource.") -> None:
        super().__init__(
            detail=detail,
            status_code=403,
            title="Forbidden",
            error_code="AUTHORIZATION_FAILED",
        )


class LLMProviderError(KathaException):
    """Raised when an LLM provider fails (network, rate limit, or model error)."""

    def __init__(self, provider: str, detail: str, original_error: str | None = None) -> None:
        super().__init__(
            detail=f"LLM Provider [{provider}] failed: {detail}",
            status_code=502,
            title="LLM Provider Error",
            error_code="LLM_PROVIDER_ERROR",
            extras={"provider": provider, "original_error": original_error},
        )


class SchemaValidationError(KathaException):
    """Raised when LLM response cannot be parsed into the expected Pydantic schema."""

    def __init__(self, schema_name: str, raw_output: str, error_detail: str) -> None:
        super().__init__(
            detail=f"Failed to validate LLM response against schema '{schema_name}': {error_detail}",
            status_code=502,
            title="Schema Validation Error",
            error_code="SCHEMA_VALIDATION_ERROR",
            extras={"schema_name": schema_name, "raw_output": raw_output[:1000]},
        )

