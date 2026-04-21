import asyncio
import json
import time
from dataclasses import dataclass, field
from fastapi import WebSocket


@dataclass
class ConnectedUser:
    user_id: int
    username: str
    websocket: WebSocket
    is_muted: bool = False


class RoomConnectionManager:
    """Barcha active xonalar va ulardagi WebSocket ulanishlarni boshqaradi."""

    def __init__(self):
        # room_code -> {user_id -> ConnectedUser}
        self._rooms: dict[str, dict[int, ConnectedUser]] = {}

    def get_room_users(self, room_code: str) -> list[ConnectedUser]:
        return list(self._rooms.get(room_code, {}).values())

    async def connect(self, room_code: str, user: ConnectedUser):
        if room_code not in self._rooms:
            self._rooms[room_code] = {}
        self._rooms[room_code][user.user_id] = user
        await user.websocket.accept()

    def disconnect(self, room_code: str, user_id: int):
        if room_code in self._rooms:
            self._rooms[room_code].pop(user_id, None)
            if not self._rooms[room_code]:
                del self._rooms[room_code]

    async def send_to(self, user_id: int, room_code: str, message: dict):
        users = self._rooms.get(room_code, {})
        user = users.get(user_id)
        if user:
            try:
                await user.websocket.send_text(json.dumps(message))
            except Exception:
                self.disconnect(room_code, user_id)

    async def broadcast(self, room_code: str, message: dict, exclude_user_id: int | None = None):
        """Xonadagi barcha foydalanuvchilarga yuborish (ixtiyoriy ravishda bittasini chiqarib tashlab)."""
        users = list(self._rooms.get(room_code, {}).values())
        dead = []
        payload = json.dumps(message)
        for user in users:
            if exclude_user_id and user.user_id == exclude_user_id:
                continue
            try:
                await user.websocket.send_text(payload)
            except Exception:
                dead.append(user.user_id)
        for uid in dead:
            self.disconnect(room_code, uid)

    def room_user_count(self, room_code: str) -> int:
        return len(self._rooms.get(room_code, {}))

    def set_mute(self, room_code: str, user_id: int, muted: bool):
        if room_code in self._rooms and user_id in self._rooms[room_code]:
            self._rooms[room_code][user_id].is_muted = muted


# Global instance
manager = RoomConnectionManager()
