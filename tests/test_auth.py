import pytest
from httpx import AsyncClient


REGISTER_DATA = {
    "username": "testuser",
    "email": "test@example.com",
    "password": "securepass123",
}


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    res = await client.post("/auth/register", json=REGISTER_DATA)
    assert res.status_code == 201
    body = res.json()
    assert "access_token" in body
    assert body["user"]["username"] == "testuser"
    assert body["user"]["email"] == "test@example.com"
    # Parol hech qachon javobda bo'lmasligi kerak
    assert "password" not in body["user"]
    assert "hashed_password" not in body["user"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    await client.post("/auth/register", json=REGISTER_DATA)
    res = await client.post("/auth/register", json=REGISTER_DATA)
    assert res.status_code == 400
    assert "already registered" in res.json()["detail"]


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post("/auth/register", json=REGISTER_DATA)
    res = await client.post("/auth/login", json={
        "email": REGISTER_DATA["email"],
        "password": REGISTER_DATA["password"],
    })
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post("/auth/register", json=REGISTER_DATA)
    res = await client.post("/auth/login", json={
        "email": REGISTER_DATA["email"],
        "password": "wrongpassword",
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient):
    res = await client.post("/auth/login", json={
        "email": "nobody@example.com",
        "password": "any",
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient):
    reg = await client.post("/auth/register", json=REGISTER_DATA)
    token = reg.json()["access_token"]
    res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["email"] == REGISTER_DATA["email"]


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    res = await client.get("/auth/me")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    res = await client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert res.status_code == 401
