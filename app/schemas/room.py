from pydantic import BaseModel, HttpUrl
from datetime import datetime


class RoomCreate(BaseModel):
    name: str
    video_url: str | None = None


class RoomJoin(BaseModel):
    code: str


class RoomOut(BaseModel):
    id: int
    code: str
    name: str
    host_id: int
    video_url: str | None
    current_position: float
    is_playing: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RoomSetVideo(BaseModel):
    video_url: str


class MessageOut(BaseModel):
    id: int
    user_id: int
    username: str
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}
