import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_episodes(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Create Series
    series_res = await client.post(
        "/api/v1/series",
        json={"title": "Series Alpha", "logline": "Logline Alpha", "genre": "mystery"},
        headers=auth_headers,
    )
    series_id = series_res.json()["id"]

    # Create Episode 1
    ep1_payload = {
        "series_id": series_id,
        "episode_number": 1,
        "title": "The Awakening",
        "premise": "The story begins on a rainy evening when the clock strikes twelve.",
        "target_language": "hindi",
        "duration_minutes_target": 5,
    }
    ep1_res = await client.post("/api/v1/episodes", json=ep1_payload, headers=auth_headers)
    assert ep1_res.status_code == 201
    ep1_data = ep1_res.json()
    assert ep1_data["title"] == "The Awakening"
    assert ep1_data["status"] == "DRAFT"

    # List episodes for series
    list_res = await client.get(f"/api/v1/episodes/series/{series_id}", headers=auth_headers)
    assert list_res.status_code == 200
    episodes = list_res.json()
    assert len(episodes) == 1
    assert episodes[0]["id"] == ep1_data["id"]


@pytest.mark.asyncio
async def test_episode_ownership_security(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    # User A creates a series
    series_res = await client.post(
        "/api/v1/series",
        json={"title": "User A Series", "logline": "Strictly confidential", "genre": "drama"},
        headers=auth_headers,
    )
    series_id = series_res.json()["id"]

    # User B attempts to create episode inside User A's series -> 403 Forbidden
    unauthorized_ep = {
        "series_id": series_id,
        "episode_number": 1,
        "title": "Malicious Episode",
        "premise": "Trying to inject episode into someone else's series.",
    }
    res = await client.post("/api/v1/episodes", json=unauthorized_ep, headers=other_auth_headers)
    assert res.status_code == 403
    assert res.json()["error_code"] == "AUTHORIZATION_FAILED"


@pytest.mark.asyncio
async def test_generate_episode_outline_endpoint(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    series_res = await client.post(
        "/api/v1/series",
        json={"title": "Radio Mystery", "logline": "Late night radio secrets", "genre": "thriller"},
        headers=auth_headers,
    )
    series_id = series_res.json()["id"]

    outline_req = {
        "series_id": series_id,
        "episode_number": 1,
        "premise": "A late night radio DJ gets a call from 1947 Chandni Chowk.",
        "target_language": "hinglish",
        "target_duration_minutes": 5,
        "genre": "thriller",
        "characters_hint": ["Kabir", "Ananya"],
    }
    res = await client.post(
        "/api/v1/episodes/generate-outline",
        json=outline_req,
        headers=auth_headers,
    )
    assert res.status_code == 200
    outline = res.json()
    assert "title" in outline
    assert "scenes" in outline
    assert len(outline["scenes"]) >= 1
    assert "characters" in outline
    assert len(outline["characters"]) >= 1
    assert "cliffhanger_or_resolution" in outline
