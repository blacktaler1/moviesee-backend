import random
import string
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.room import Room, Message


def generate_room_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


async def create_room(db: AsyncSession, name: str, host_id: int, video_url: str | None = None) -> Room:
    # Unikal kod yaratish
    for _ in range(10):
        code = generate_room_code()
        existing = await db.execute(select(Room).where(Room.code == code))
        if not existing.scalar_one_or_none():
            break

    room = Room(code=code, name=name, host_id=host_id, video_url=video_url)
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


async def get_room_by_code(db: AsyncSession, code: str) -> Room | None:
    result = await db.execute(select(Room).where(Room.code == code.upper()))
    return result.scalar_one_or_none()


async def get_room_by_id(db: AsyncSession, room_id: int) -> Room | None:
    result = await db.execute(select(Room).where(Room.id == room_id))
    return result.scalar_one_or_none()


async def update_room_video(db: AsyncSession, room: Room, video_url: str) -> Room:
    room.video_url = video_url
    await db.commit()
    await db.refresh(room)
    return room


async def update_room_playback(db: AsyncSession, room: Room, position: float, is_playing: bool) -> None:
    room.current_position = position
    room.is_playing = is_playing
    await db.commit()


async def save_message(db: AsyncSession, room_id: int, user_id: int, text: str) -> Message:
    msg = Message(room_id=room_id, user_id=user_id, text=text)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def get_room_messages(db: AsyncSession, room_id: int, limit: int = 50) -> list[Message]:
    result = await db.execute(
        select(Message).where(Message.room_id == room_id).order_by(Message.created_at.desc()).limit(limit)
    )
    return list(reversed(result.scalars().all()))
