from datetime import datetime
from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    video_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    current_position: Mapped[float] = mapped_column(Float, default=0.0)
    is_playing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(back_populates="room", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    room: Mapped["Room"] = relationship(back_populates="messages")
    user: Mapped["User"] = relationship(back_populates="messages")  # noqa: F821
