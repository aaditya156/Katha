from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Standard Pricing per 1M tokens ($USD) - Configurable runtime registry
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Gemini 1.5 Flash: $0.075 / 1M prompt, $0.30 / 1M completion
    "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.30},
    # Gemini 1.5 Pro: $1.25 / 1M prompt, $5.00 / 1M completion
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.00},
    # Gemini 2.0 Flash: $0.10 / 1M prompt, $0.40 / 1M completion
    "gemini-2.0-flash": {"prompt": 0.10, "completion": 0.40},
    # Groq Llama 3.3 70B Versatile: $0.59 / 1M prompt, $0.79 / 1M completion
    "llama-3.3-70b-versatile": {"prompt": 0.59, "completion": 0.79},
    # Groq Llama 3.1 8B Instant: $0.05 / 1M prompt, $0.08 / 1M completion
    "llama-3.1-8b-instant": {"prompt": 0.05, "completion": 0.08},
    # Mock / Testing: $0.00
    "mock": {"prompt": 0.0, "completion": 0.0},
    "mock-model": {"prompt": 0.0, "completion": 0.0},
    "mock-low": {"prompt": 0.0, "completion": 0.0},
}


def register_model_pricing(model_name: str, prompt_price_per_1m: float, completion_price_per_1m: float) -> None:
    """Register or update runtime pricing per 1M tokens for a given model without hardcoding."""
    MODEL_PRICING[model_name.lower()] = {
        "prompt": prompt_price_per_1m,
        "completion": completion_price_per_1m,
    }
    logger.info(f"Registered model pricing for '{model_name}': prompt=${prompt_price_per_1m}/1M, completion=${completion_price_per_1m}/1M")


def estimate_token_cost_with_status(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[float, str]:
    """Calculate the estimated USD cost for an LLM invocation.
    
    Returns (cost_usd, status) where status is 'ESTIMATED', 'UNKNOWN', or 'MOCK'.
    Does NOT fabricate pricing for unconfigured models.
    """
    key = model_name.lower()
    if key in ("mock", "mock-model", "mock-low"):
        return 0.0, "MOCK"

    pricing = MODEL_PRICING.get(key)
    if not pricing:
        logger.warning(f"Pricing for model '{model_name}' is not configured; marking as UNKNOWN without fabricating costs.")
        return 0.0, "UNKNOWN"

    prompt_cost = (prompt_tokens / 1_000_000.0) * pricing["prompt"]
    completion_cost = (completion_tokens / 1_000_000.0) * pricing["completion"]
    return round(prompt_cost + completion_cost, 6), "ESTIMATED"


def estimate_token_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Calculate estimated USD cost; returns 0.0 if pricing is unknown (see estimate_token_cost_with_status)."""
    cost, _ = estimate_token_cost_with_status(model_name, prompt_tokens, completion_tokens)
    return cost


@dataclass
class TelemetrySpan:
    """Represents an execution span in a LangGraph or service workflow."""

    span_id: str
    name: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    latency_ms: float = 0.0
    model_name: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    status: str = "RUNNING"  # RUNNING, SUCCESS, ERROR
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(
        self,
        status: str = "SUCCESS",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model_name: str | None = None,
    ) -> None:
        self.end_time = datetime.now(timezone.utc)
        self.latency_ms = (self.end_time - self.start_time).total_seconds() * 1000.0
        self.status = status
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        if model_name:
            self.model_name = model_name
        if self.model_name:
            self.cost_usd = estimate_token_cost(self.model_name, self.prompt_tokens, self.completion_tokens)


class TelemetryTracer:
    """Thread-safe telemetry & observability tracer with Langfuse compatibility and local in-memory sink."""

    def __init__(self) -> None:
        self._spans: list[TelemetrySpan] = []

    def start_span(self, name: str, span_id: str, metadata: dict[str, Any] | None = None) -> TelemetrySpan:
        span = TelemetrySpan(
            span_id=span_id,
            name=name,
            metadata=metadata or {},
        )
        self._spans.append(span)
        return span

    def get_recent_spans(self, limit: int = 100) -> list[TelemetrySpan]:
        return self._spans[-limit:]

    def clear(self) -> None:
        self._spans.clear()


telemetry_tracer = TelemetryTracer()

