"""
WebSocket event handler.

Har bir xabар turi uchun alohida handler.
Client → Server → broadcast pattern ishlatiladi.
"""
import time
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.websocket.manager import manager, ConnectedUser
from app.models.user import User
from app.services.room import (
    get_room_by_code,
    update_room_playback,
    save_message,
)

logger = logging.getLogger(__name__)


async def handle_websocket(
    websocket: WebSocket,
    room_code: str,
    current_user: User,
    db: AsyncSession,
):
    room = await get_room_by_code(db, room_code)
    if not room:
        logger.warning(f"[WS/events] Xona topilmadi: room={room_code}, user={current_user.username}")
        await websocket.close(code=4004, reason="Room not found")
        return

    conn_user = ConnectedUser(
        user_id=current_user.id,
        username=current_user.username,
        websocket=websocket,
    )

    await manager.connect(room_code, conn_user)
    online_count = manager.room_user_count(room_code)
    logger.info(f"[WS/events] User ulandi: user={current_user.username}({current_user.id}), room={room_code}, online={online_count}")

    # Yangi foydalanuvchiga joriy holat va chat tarixini yuborish
    await manager.send_to(current_user.id, room_code, {
        "type": "room_state",
        "video_url": room.video_url,
        "position": room.current_position,
        "playing": room.is_playing,
        "server_time": time.time(),
        "users": [
            {"user_id": u.user_id, "username": u.username, "muted": u.is_muted}
            for u in manager.get_room_users(room_code)
        ],
    })

    # Boshqa foydalanuvchilarga yangi odam kirdi xabari
    await manager.broadcast(room_code, {
        "type": "user_joined",
        "user_id": current_user.id,
        "username": current_user.username,
    }, exclude_user_id=current_user.id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type")
            logger.debug(f"[WS/events] Event: type={event_type}, user={current_user.username}({current_user.id}), room={room_code}")

            # ── Playback events (faqat host yoki hamma? — hamma uchun ochiq) ──
            if event_type == "play":
                position = float(data.get("position", 0))
                room.current_position = position
                room.is_playing = True
                await update_room_playback(db, room, position, True)
                await manager.broadcast(room_code, {
                    "type": "sync_state",
                    "position": position,
                    "playing": True,
                    "server_time": time.time(),
                    "by_user": current_user.id,
                })

            elif event_type == "pause":
                position = float(data.get("position", 0))
                room.current_position = position
                room.is_playing = False
                await update_room_playback(db, room, position, False)
                await manager.broadcast(room_code, {
                    "type": "sync_state",
                    "position": position,
                    "playing": False,
                    "server_time": time.time(),
                    "by_user": current_user.id,
                })

            elif event_type == "seek":
                position = float(data.get("position", 0))
                room.current_position = position
                await update_room_playback(db, room, position, room.is_playing)
                await manager.broadcast(room_code, {
                    "type": "sync_state",
                    "position": position,
                    "playing": room.is_playing,
                    "server_time": time.time(),
                    "by_user": current_user.id,
                }, exclude_user_id=current_user.id)

            elif event_type == "request_sync":
                # Joriy holatni so'ragan foydalanuvchiga yuborish
                await manager.send_to(current_user.id, room_code, {
                    "type": "sync_state",
                    "position": room.current_position,
                    "playing": room.is_playing,
                    "server_time": time.time(),
                })

            elif event_type == "set_video":
                video_url = data.get("url", "").strip()
                if video_url:
                    room.video_url = video_url
                    room.current_position = 0
                    room.is_playing = True
                    await db.commit()
                    logger.info(f"[WS/events] set_video: room={room_code}, url={video_url[:60]}...")
                    await manager.broadcast(room_code, {
                        "type": "video_changed",
                        "url": video_url,
                        "playing": True,
                        "position": 0,
                        "by_user": current_user.id,
                    })

            # ── Chat ──
            elif event_type == "chat":
                text = data.get("text", "").strip()
                if text and len(text) <= 500:
                    msg = await save_message(db, room.id, current_user.id, text)
                    await manager.broadcast(room_code, {
                        "type": "chat_message",
                        "user_id": current_user.id,
                        "username": current_user.username,
                        "text": text,
                        "time": msg.created_at.strftime("%H:%M"),
                    })

            # ── Mikrofon holati ──
            elif event_type == "mute":
                muted = bool(data.get("muted", False))
                manager.set_mute(room_code, current_user.id, muted)
                await manager.broadcast(room_code, {
                    "type": "mute_status",
                    "user_id": current_user.id,
                    "muted": muted,
                })

            # ── WebRTC Signaling ──
            elif event_type in ("webrtc_offer", "webrtc_answer", "webrtc_ice"):
                target_id = data.get("to_user")
                if target_id:
                    logger.debug(f"[WS/events] WebRTC signal: {event_type} | from={current_user.id} → to={target_id}")
                    await manager.send_to(int(target_id), room_code, {
                        **data,
                        "from_user": current_user.id,
                    })
                else:
                    logger.warning(f"[WS/events] WebRTC signal 'to_user' yo'q: type={event_type}, from={current_user.id}")

    except WebSocketDisconnect:
        logger.info(f"[WS/events] User uzildi: user={current_user.username}({current_user.id}), room={room_code}")
    except Exception:
        logger.error(f"[WS/events] Kutilmagan xato: user={current_user.username}, room={room_code}", exc_info=True)
    finally:
        manager.disconnect(room_code, current_user.id)
        remaining = manager.room_user_count(room_code)
        logger.info(f"[WS/events] User chiqdi: user={current_user.username}, room={room_code}, qolganlar={remaining}")
        await manager.broadcast(room_code, {
            "type": "user_left",
            "user_id": current_user.id,
            "username": current_user.username,
        })
