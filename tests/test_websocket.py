"""
WebSocket sinxronizatsiya testlari.
fastapi.testclient.TestClient WebSocket testlarni qo'llab-quvvatlaydi.
"""
import json
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app


# ── Helper ───────────────────────────────────────────────────

async def setup_room(client: AsyncClient, suffix: str) -> tuple[str, str]:
    """Foydalanuvchi yaratib, xona ochadi. (token, room_code) qaytaradi."""
    reg = await client.post("/auth/register", json={
        "username": f"ws{suffix}",
        "email": f"ws{suffix}@test.com",
        "password": "pass1234",
    })
    token = reg.json()["access_token"]
    room = await client.post(
        "/rooms/create",
        json={"name": f"WS xona {suffix}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return token, room.json()["code"]


# ── Testlar ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_connect_and_receive_room_state(client: AsyncClient):
    token, code = await setup_room(client, "1")
    sync_client = TestClient(app)

    with sync_client.websocket_connect(f"/ws/{code}?token={token}") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "room_state"
        assert "position" in msg
        assert "playing" in msg
        assert "users" in msg


@pytest.mark.asyncio
async def test_ws_invalid_token_rejected(client: AsyncClient):
    _, code = await setup_room(client, "2")
    sync_client = TestClient(app)

    with pytest.raises(Exception):
        with sync_client.websocket_connect(f"/ws/{code}?token=bad.token") as ws:
            ws.receive_text()


@pytest.mark.asyncio
async def test_ws_invalid_room_rejected(client: AsyncClient):
    token, _ = await setup_room(client, "3")
    sync_client = TestClient(app)

    with pytest.raises(Exception):
        with sync_client.websocket_connect(f"/ws/NOROOM?token={token}") as ws:
            ws.receive_text()


@pytest.mark.asyncio
async def test_ws_play_broadcast(client: AsyncClient):
    token, code = await setup_room(client, "4")
    sync_client = TestClient(app)

    with sync_client.websocket_connect(f"/ws/{code}?token={token}") as ws:
        ws.receive_text()  # room_state

        # play yuborish
        ws.send_text(json.dumps({"type": "play", "position": 42.5}))
        msg = json.loads(ws.receive_text())

        assert msg["type"] == "sync_state"
        assert msg["playing"] is True
        assert msg["position"] == pytest.approx(42.5, abs=0.1)


@pytest.mark.asyncio
async def test_ws_pause_broadcast(client: AsyncClient):
    token, code = await setup_room(client, "5")
    sync_client = TestClient(app)

    with sync_client.websocket_connect(f"/ws/{code}?token={token}") as ws:
        ws.receive_text()  # room_state

        ws.send_text(json.dumps({"type": "pause", "position": 100.0}))
        msg = json.loads(ws.receive_text())

        assert msg["type"] == "sync_state"
        assert msg["playing"] is False
        assert msg["position"] == pytest.approx(100.0, abs=0.1)


@pytest.mark.asyncio
async def test_ws_chat_message(client: AsyncClient):
    token, code = await setup_room(client, "6")
    sync_client = TestClient(app)

    with sync_client.websocket_connect(f"/ws/{code}?token={token}") as ws:
        ws.receive_text()  # room_state

        ws.send_text(json.dumps({"type": "chat", "text": "Salom!"}))
        msg = json.loads(ws.receive_text())

        assert msg["type"] == "chat_message"
        assert msg["text"] == "Salom!"
        assert msg["username"] == "ws6"


@pytest.mark.asyncio
async def test_ws_mute_status(client: AsyncClient):
    token, code = await setup_room(client, "7")
    sync_client = TestClient(app)

    with sync_client.websocket_connect(f"/ws/{code}?token={token}") as ws:
        ws.receive_text()  # room_state

        ws.send_text(json.dumps({"type": "mute", "muted": True}))
        msg = json.loads(ws.receive_text())

        assert msg["type"] == "mute_status"
        assert msg["muted"] is True
