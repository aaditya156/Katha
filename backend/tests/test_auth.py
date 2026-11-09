import pytest
from httpx import AsyncClient
from app.models.user import User


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient) -> None:
    payload = {
        "email": "newcreator@katha.studio",
        "password": "Password123!",
        "full_name": "New Katha Author",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "newcreator@katha.studio"
    assert data["user"]["full_name"] == "New Katha Author"
    assert "password" not in data["user"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_user: User) -> None:
    payload = {
        "email": test_user.email,
        "password": "AnotherPassword123!",
        "full_name": "Imposter",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["error_code"] == "DUPLICATE_ENTITY"
    assert "already exists" in data["detail"]


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user: User) -> None:
    payload = {
        "email": test_user.email,
        "password": "StrongPassword123!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient, test_user: User) -> None:
    payload = {
        "email": test_user.email,
        "password": "WrongPassword!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == "AUTHENTICATION_FAILED"


@pytest.mark.asyncio
async def test_get_current_user_profile(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_user.id
    assert data["email"] == test_user.email


@pytest.mark.asyncio
async def test_protected_route_without_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == "AUTHENTICATION_FAILED"


@pytest.mark.asyncio
async def test_token_refresh(client: AsyncClient, test_user: User) -> None:
    # First login to get a fresh refresh token
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "StrongPassword123!"},
    )
    refresh_token = login_res.json()["refresh_token"]

    response = await client.post(f"/api/v1/auth/refresh?refresh_token={refresh_token}")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data

