import asyncio
from typing import Any, TypeVar
from pydantic import BaseModel
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.outline import CharacterAppearance, DramaticBeat, EpisodeOutline, SceneOutline

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider(BaseLLMProvider):
    """Deterministic Mock LLM Provider for unit, integration, and CI testing."""

    def __init__(self, mode: str = "normal", delay_seconds: float = 0.0) -> None:
        self.mode = mode
        self.delay_seconds = delay_seconds

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        if self.mode == "timeout":
            raise LLMProviderError("mock", "Request timed out after 30.0s", "TimeoutError")

        if self.mode == "provider_failure":
            raise LLMProviderError("mock", "Service temporarily overloaded (HTTP 503)", "Upstream503")

        if self.mode == "malformed_json":
            raise SchemaValidationError(
                schema.__name__,
                raw_output="{'invalid_json': true,",
                error_detail="JSONDecodeError: Expecting value at line 1 column 22",
            )

        if self.mode == "schema_error":
            raise SchemaValidationError(
                schema.__name__,
                raw_output='{"unexpected_field": "test"}',
                error_detail="Field required: missing required schema keys",
            )

        # Normal mode: Return realistic structured instance
        if schema == EpisodeOutline:
            mock_data: dict[str, Any] = {
                "title": "Purani Dilli Ki Dastak (पुरानी दिल्ली की दस्तक)",
                "logline": "Late at night in Chandni Chowk, a radio RJ receives a call from someone claiming to be broadcast from 1947.",
                "target_language": "hinglish",
                "estimated_duration_minutes": 5,
                "characters": [
                    {
                        "name": "Kabir",
                        "role": "protagonist",
                        "vocal_archetype": "warm late-night RJ baritone",
                        "emotional_state": "intrigued then increasingly unsettled",
                    },
                    {
                        "name": "Ananya",
                        "role": "supporting",
                        "vocal_archetype": "sharp energetic producer alto",
                        "emotional_state": "skeptical, deadline-driven",
                    },
                    {
                        "name": "The Caller",
                        "role": "antagonist",
                        "vocal_archetype": "crackle-laden, trembling vintage voice",
                        "emotional_state": "desperate and nostalgic",
                    },
                ],
                "scenes": [
                    {
                        "scene_number": 1,
                        "heading": "INT. RADIO MIRAGE STUDIO - MIDNIGHT",
                        "atmosphere_soundscape": "Low air-conditioner hum, studio mic presence, console clicks",
                        "characters_present": ["Kabir", "Ananya"],
                        "dramatic_objective": "Establish Kabir's mundane graveyard shift before the supernatural intrusion.",
                        "beats": [
                            {
                                "beat_number": 1,
                                "description": "Kabir wraps up a Bollywood ballad and opens phone lines for midnight confessions.",
                                "conflict_type": "interpersonal",
                                "stakes": "Producer threatens to cancel the show if listener engagement drops.",
                            },
                            {
                                "beat_number": 2,
                                "description": "Console lights flicker erratically; an unrouted analogue telephone frequency overrides the digital mixer.",
                                "conflict_type": "environmental",
                                "stakes": "Audio transmission integrity is compromised.",
                            },
                        ],
                    },
                    {
                        "scene_number": 2,
                        "heading": "INT. RADIO MIRAGE STUDIO - CONTINUOUS",
                        "atmosphere_soundscape": "Heavy static, Morse code hum in the sub-bass, distant sound of old tram bells",
                        "characters_present": ["Kabir", "The Caller"],
                        "dramatic_objective": "The Caller speaks with eerie authenticity about specific locations in 1947 Delhi.",
                        "beats": [
                            {
                                "beat_number": 1,
                                "description": "The Caller addresses Kabir by his grandfather's forgotten childhood nickname.",
                                "conflict_type": "interpersonal",
                                "stakes": "Kabir realizes this is not a prank caller.",
                            },
                        ],
                    },
                ],
                "cliffhanger_or_resolution": "The Caller transmits the exact sound of a train departing, followed by dead air. A telegram from 1947 is found on Kabir's real-world desk.",
            }
            return schema.model_validate(mock_data)

        # Generic fallback attempt using schema defaults or empty construct
        try:
            return schema.model_validate({})
        except Exception as exc:
            raise SchemaValidationError(schema.__name__, "{}", str(exc))

    async def generate_chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        if self.mode == "provider_failure":
            raise LLMProviderError("mock", "Service temporarily overloaded (HTTP 503)", "Upstream503")
        return f"Mock response for prompt: {prompt[:50]}..."
