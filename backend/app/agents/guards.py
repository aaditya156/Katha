import asyncio
import logging
from typing import Any, TypeVar
from pydantic import BaseModel
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


async def generate_structured_with_guardrail(
    llm: BaseLLMProvider,
    prompt: str,
    schema: type[T],
    system_prompt: str | None = None,
    max_retries: int = 2,
    node_name: str = "agent",
) -> T:
    """Execute structured LLM generation with bounded retries and schema repair feedback.

    If the LLM returns invalid JSON or the output violates the Pydantic schema,
    the validation error details are injected into a repair prompt for subsequent
    attempts (up to max_retries).

    Args:
        llm: The LLM provider instance conforming to BaseLLMProvider.
        prompt: The user/task prompt.
        schema: Target Pydantic model class.
        system_prompt: Optional system instruction.
        max_retries: Maximum number of correction attempts after an initial failure (default 2).
        node_name: Calling agent node name for structured logging.

    Returns:
        Validated instance of schema T.

    Raises:
        SchemaValidationError: If output fails validation after all retry attempts.
        LLMProviderError: If upstream API call encounters fatal network or auth errors.
    """
    total_attempts = max_retries + 1
    current_prompt = prompt
    last_schema_error: SchemaValidationError | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            logger.info(
                f"[{node_name}] Invoking structured generation for schema '{schema.__name__}' "
                f"(Attempt {attempt}/{total_attempts})"
            )
            result = await llm.generate_structured(
                prompt=current_prompt,
                schema=schema,
                system_prompt=system_prompt,
            )
            if attempt > 1:
                logger.info(
                    f"[{node_name}] Schema validation recovered successfully on attempt {attempt} "
                    f"for schema '{schema.__name__}'."
                )
            return result

        except SchemaValidationError as exc:
            last_schema_error = exc
            raw_out = getattr(exc, "raw_output", None) or exc.extras.get("raw_output", "")
            logger.warning(
                f"[{node_name}] Schema validation failed on attempt {attempt}/{total_attempts} "
                f"for '{schema.__name__}': {exc.detail}"
            )
            if attempt < total_attempts:
                # Augment prompt with schema repair instructions
                repair_feedback = (
                    f"\n\n[ATTENTION - CRITICAL SCHEMA REPAIR REQUIRED (Attempt {attempt}/{max_retries})]:\n"
                    f"Your previous response failed validation against the required schema '{schema.__name__}'.\n"
                    f"Validation Error Details:\n{exc.detail or str(exc)}\n"
                    f"Raw Output Snippet:\n{raw_out[:400] if raw_out else 'N/A'}\n"
                    f"Action Required: Rectify all missing, incorrectly typed, or invalid fields. "
                    f"Return ONLY valid JSON strictly matching the '{schema.__name__}' schema."
                )
                current_prompt = f"{prompt}{repair_feedback}"
                await asyncio.sleep(0.3 * attempt)
            else:
                logger.error(
                    f"[{node_name}] Exhausted all {total_attempts} attempts for schema '{schema.__name__}'. "
                    f"Final error: {exc.detail}"
                )
                raise SchemaValidationError(
                    schema_name=schema.__name__,
                    raw_output=raw_out,
                    error_detail=f"Exhausted {total_attempts} attempts without valid schema: {exc.detail}",
                ) from exc

        except LLMProviderError as exc:
            # Handle transient upstream rate limits or timeouts
            is_transient = "429" in str(exc) or "503" in str(exc) or "timeout" in str(exc).lower()
            if is_transient and attempt < total_attempts:
                backoff = 0.5 * (2 ** (attempt - 1))
                logger.warning(
                    f"[{node_name}] Transient upstream LLM error on attempt {attempt}/{total_attempts}: {exc}. "
                    f"Retrying in {backoff:.1f}s..."
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    f"[{node_name}] Non-recoverable LLM error on attempt {attempt}: {exc}",
                    exc_info=True,
                )
                raise

    if last_schema_error is not None:
        raise last_schema_error
    raise SchemaValidationError(schema.__name__, "Unknown error", "No valid schema generated.")
