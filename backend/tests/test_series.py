import pytest
from httpx import AsyncClient
from app.models.user import User


@pytest.mark.asyncio
async def test_create_series(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    payload = {
        "title": "Dilli Darpan (दिल्ली दर्पण)",
        "genre": "psychological thriller",
        "logline": "An investigative journalist uncovers an underground radio broadcast whispering secrets of historical Delhi.",
        "target_language": "hinglish",
    }
    response = await client.post("/api/v1/series", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == payload["title"]
    assert data["user_id"] == test_user.id
    assert data["target_language"] == "hinglish"


@pytest.mark.asyncio
async def test_list_series_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    # Test User creates a series
    await client.post(
        "/api/v1/series",
        json={"title": "Series A", "logline": "Logline for series A", "genre": "drama"},
        headers=auth_headers,
    )

    # Other User creates a series
    await client.post(
        "/api/v1/series",
        json={"title": "Series B", "logline": "Logline for series B", "genre": "sci-fi"},
        headers=other_auth_headers,
    )

    # Test User lists series -> should only see Series A
    res_a = await client.get("/api/v1/series", headers=auth_headers)
    assert res_a.status_code == 200
    list_a = res_a.json()
    assert len(list_a) == 1
    assert list_a[0]["title"] == "Series A"

    # Other User lists series -> should only see Series B
    res_b = await client.get("/api/v1/series", headers=other_auth_headers)
    assert res_b.status_code == 200
    list_b = res_b.json()
    assert len(list_b) == 1
    assert list_b[0]["title"] == "Series B"


@pytest.mark.asyncio
async def test_ownership_enforcement_on_get_and_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    # User A creates a series
    create_res = await client.post(
        "/api/v1/series",
        json={"title": "Private Series", "logline": "Confidential story logline", "genre": "horror"},
        headers=auth_headers,
    )
    series_id = create_res.json()["id"]

    # User B tries to view User A's series -> 403 Forbidden
    get_res = await client.get(f"/api/v1/series/{series_id}", headers=other_auth_headers)
    assert get_res.status_code == 403
    assert get_res.json()["error_code"] == "AUTHORIZATION_FAILED"

    # User B tries to update User A's series -> 403 Forbidden
    update_res = await client.put(
        f"/api/v1/series/{series_id}",
        json={"title": "Hacked Title"},
        headers=other_auth_headers,
    )
    assert update_res.status_code == 403

    # User B tries to delete User A's series -> 403 Forbidden
    delete_res = await client.delete(f"/api/v1/series/{series_id}", headers=other_auth_headers)
    assert delete_res.status_code == 403

    # User A successfully updates
    valid_update = await client.put(
        f"/api/v1/series/{series_id}",
        json={"title": "Legitimate Update"},
        headers=auth_headers,
    )
    assert valid_update.status_code == 200
    assert valid_update.json()["title"] == "Legitimate Update"

    # User A successfully deletes
    valid_delete = await client.delete(f"/api/v1/series/{series_id}", headers=auth_headers)
    assert valid_delete.status_code == 204

