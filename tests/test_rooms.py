import pytest
from httpx import AsyncClient


# ── Helper ───────────────────────────────────────────────────

async def register_and_login(client: AsyncClient, suffix: str = "") -> str:
    """Foydalanuvchi yaratib token qaytaradi."""
    data = {
        "username": f"user{suffix}",
        "email": f"user{suffix}@example.com",
        "password": "pass1234",
    }
    res = await client.post("/auth/register", json=data)
    return res.json()["access_token"]


# ── Testlar ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_room(client: AsyncClient):
    token = await register_and_login(client, "room1")
    res = await client.post(
        "/rooms/create",
        json={"name": "Kino kechasi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Kino kechasi"
    assert len(body["code"]) == 6
    assert body["is_playing"] is False
    assert body["current_position"] == 0.0


@pytest.mark.asyncio
async def test_create_room_requires_auth(client: AsyncClient):
    res = await client.post("/rooms/create", json={"name": "test"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_join_room_success(client: AsyncClient):
    # Host xona yaratadi
    host_token = await register_and_login(client, "host1")
    create_res = await client.post(
        "/rooms/create",
        json={"name": "Birgalikda"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    code = create_res.json()["code"]

    # Boshqa foydalanuvchi qo'shiladi
    guest_token = await register_and_login(client, "guest1")
    join_res = await client.post(
        "/rooms/join",
        json={"code": code},
        headers={"Authorization": f"Bearer {guest_token}"},
    )
    assert join_res.status_code == 200
    assert join_res.json()["code"] == code


@pytest.mark.asyncio
async def test_join_room_wrong_code(client: AsyncClient):
    token = await register_and_login(client, "join2")
    res = await client.post(
        "/rooms/join",
        json={"code": "XXXXXX"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_room(client: AsyncClient):
    token = await register_and_login(client, "get1")
    create_res = await client.post(
        "/rooms/create",
        json={"name": "Test xona"},
        headers={"Authorization": f"Bearer {token}"},
    )
    code = create_res.json()["code"]

    get_res = await client.get(
        f"/rooms/{code}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["code"] == code


@pytest.mark.asyncio
async def test_set_video_by_host(client: AsyncClient):
    token = await register_and_login(client, "vid1")
    create_res = await client.post(
        "/rooms/create",
        json={"name": "Video xona"},
        headers={"Authorization": f"Bearer {token}"},
    )
    code = create_res.json()["code"]

    patch_res = await client.patch(
        f"/rooms/{code}/video",
        json={"video_url": "https://archive.org/download/test/video.mp4"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_res.status_code == 200
    assert "archive.org" in patch_res.json()["video_url"]


@pytest.mark.asyncio
async def test_set_video_by_non_host_forbidden(client: AsyncClient):
    host_token = await register_and_login(client, "hst2")
    guest_token = await register_and_login(client, "gst2")

    create_res = await client.post(
        "/rooms/create",
        json={"name": "Cheklangan xona"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    code = create_res.json()["code"]

    patch_res = await client.patch(
        f"/rooms/{code}/video",
        json={"video_url": "https://example.com/video.mp4"},
        headers={"Authorization": f"Bearer {guest_token}"},
    )
    assert patch_res.status_code == 403


@pytest.mark.asyncio
async def test_room_code_is_unique(client: AsyncClient):
    token = await register_and_login(client, "uniq1")
    codes = set()
    for i in range(5):
        res = await client.post(
            "/rooms/create",
            json={"name": f"Xona {i}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        codes.add(res.json()["code"])
    assert len(codes) == 5
