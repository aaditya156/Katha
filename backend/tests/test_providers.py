import pytest
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.mock import MockLLMProvider
from app.schemas.outline import EpisodeOutline


@pytest.mark.asyncio
async def test_mock_provider_structured_output_valid() -> None:
    provider = MockLLMProvider(mode="normal")
    outline = await provider.generate_structured(
        prompt="A supernatural radio drama set in Old Delhi",
        schema=EpisodeOutline,
    )
    assert isinstance(outline, EpisodeOutline)
    assert outline.title != ""
    assert len(outline.characters) > 0
    assert len(outline.scenes) > 0
    for scene in outline.scenes:
        assert scene.scene_number >= 1
        assert scene.atmosphere_soundscape != ""
        assert len(scene.beats) > 0


@pytest.mark.asyncio
async def test_mock_provider_malformed_json_failure() -> None:
    provider = MockLLMProvider(mode="malformed_json")
    with pytest.raises(SchemaValidationError) as exc_info:
        await provider.generate_structured(
            prompt="Test prompt",
            schema=EpisodeOutline,
        )
    assert "Failed to validate LLM response" in str(exc_info.value)
    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "SCHEMA_VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_mock_provider_schema_mismatch_failure() -> None:
    provider = MockLLMProvider(mode="schema_error")
    with pytest.raises(SchemaValidationError) as exc_info:
        await provider.generate_structured(
            prompt="Test prompt",
            schema=EpisodeOutline,
        )
    assert exc_info.value.error_code == "SCHEMA_VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_mock_provider_service_overloaded_failure() -> None:
    provider = MockLLMProvider(mode="provider_failure")
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate_structured(
            prompt="Test prompt",
            schema=EpisodeOutline,
        )
    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "LLM_PROVIDER_ERROR"
    assert "Service temporarily overloaded" in exc_info.value.detail


@pytest.mark.asyncio
async def test_mock_provider_timeout_failure() -> None:
    provider = MockLLMProvider(mode="timeout")
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate_structured(
            prompt="Test prompt",
            schema=EpisodeOutline,
        )
    assert exc_info.value.error_code == "LLM_PROVIDER_ERROR"
    assert "timed out" in exc_info.value.detail

