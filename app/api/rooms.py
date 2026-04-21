import logging
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.room import RoomCreate, RoomOut, RoomJoin, RoomSetVideo
from app.services.room import create_room, get_room_by_code, update_room_video
from app.services.auth import get_user_by_id
from app.services.notifications import send_room_invite
from app.services.video_extractor import extract_video_url, extract_video_options
from app.api.deps import get_current_user
from app.models.user import User
from app.core.exceptions import (
    NotFoundException, ForbiddenException, BadRequestException,
    VideoExtractionException, ExternalServiceException,
)

logger = logging.getLogger(__name__)


class InviteBody(BaseModel):
    to_user_id: int


class ExtractUrlBody(BaseModel):
    url: str


class ExtractUrlOut(BaseModel):
    stream_url: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    headers: dict = {}  # YouTube va boshqalar uchun kerakli HTTP headerlar


class VideoOptionOut(BaseModel):
    title: str
    source_url: str       # extract-url ga beriladigan URL
    thumbnail: str | None = None
    duration: int | None = None  # soniyalarda


router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("/create", response_model=RoomOut, status_code=201)
async def create(
    body: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"[ROOMS] Xona yaratish: user={current_user.username}, name='{body.name}', video_url={body.video_url}")
    room = await create_room(db, body.name, current_user.id, body.video_url)
    logger.info(f"[ROOMS] Xona yaratildi: code={room.code}, id={room.id}")
    return RoomOut.model_validate(room)


@router.post("/join", response_model=RoomOut)
async def join(
    body: RoomJoin,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"[ROOMS] Xonaga kirish: user={current_user.username}, code={body.code}")
    room = await get_room_by_code(db, body.code)
    if not room:
        logger.warning(f"[ROOMS] Xona topilmadi: code={body.code}")
        raise NotFoundException("Xona")
    logger.info(f"[ROOMS] Xonaga kirildi: code={room.code}, name='{room.name}'")
    return RoomOut.model_validate(room)


@router.post("/extract-options", response_model=list[VideoOptionOut])
async def extract_options(
    body: ExtractUrlBody,
    current_user: User = Depends(get_current_user),
):
    """
    Sahifadagi BARCHA video variantlarini qaytaradi (stream URL chiqarmasdan).
    Ko'p variantli sahifalar uchun (uzmovi.tv: trailer + kino) foydalanuvchiga tanlash imkoni beradi.
    """
    url = body.url.strip()
    logger.info(f"[ROOMS/extract-options] So'rov: user={current_user.username}, url={url}")

    if not url:
        raise BadRequestException("URL bo'sh bo'lishi mumkin emas")

    try:
        options = await extract_video_options(url)
        logger.info(f"[ROOMS/extract-options] {len(options)} ta variant topildi: {[o.title for o in options]}")
    except Exception as e:
        logger.error(f"[ROOMS/extract-options] XATO: {e}", exc_info=True)
        raise VideoExtractionException(str(e))

    return [
        VideoOptionOut(
            title=opt.title,
            source_url=opt.source_url,
            thumbnail=opt.thumbnail,
            duration=opt.duration,
        )
        for opt in options
    ]


@router.post("/extract-url", response_model=ExtractUrlOut)
async def extract_url(
    body: ExtractUrlBody,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    YouTube, uzmovi.tv va boshqa saytlardan video stream URL ni chiqarib oladi.
    IP-locked URL'lar uchun backend proxy URL qaytariladi.
    """
    url = body.url.strip()
    logger.info(f"[ROOMS/extract-url] So'rov: user={current_user.username}, url={url}")

    if not url:
        raise BadRequestException("URL bo'sh bo'lishi mumkin emas")

    try:
        info = await extract_video_url(url)
        logger.info(
            f"[ROOMS/extract-url] ✅ title='{info.title}', "
            f"needs_proxy={info.needs_proxy}, url={info.stream_url[:80]}..."
        )
    except Exception as e:
        logger.error(f"[ROOMS/extract-url] XATO: {e}", exc_info=True)
        raise VideoExtractionException(str(e))

    # IP-locked URL'lar uchun backend proxy URL qaytaramiz
    if info.needs_proxy:
        encoded = urllib.parse.quote(url, safe="")
        base = str(request.base_url).rstrip("/")
        proxy_url = f"{base}/rooms/proxy-stream?url={encoded}"
        logger.info(f"[ROOMS/extract-url] Proxy URL qaytarilmoqda: {proxy_url[:100]}...")
        return ExtractUrlOut(
            stream_url=proxy_url,
            title=info.title,
            thumbnail=info.thumbnail,
            duration=info.duration,
            headers={},  # Proxy o'zi header'larni boshqaradi
        )

    return ExtractUrlOut(
        stream_url=info.stream_url,
        title=info.title,
        thumbnail=info.thumbnail,
        duration=info.duration,
        headers=info.headers,
    )


@router.get("/proxy-stream")
async def proxy_stream(
    url: str,
    request: Request,
):
    """
    Video stream ni CDN dan proxy qiladi.
    IP-lock muammosini hal etadi: CDN backend IP'dan so'rov qabul qiladi,
    backend esa telefonga uzatadi.
    """
    original_url = urllib.parse.unquote(url)
    logger.info(f"[ROOMS/proxy-stream] So'rov: url={original_url[:80]}...")

    # CDN URL ni olish (cache'dan yoki yangi extraction)
    try:
        info = await extract_video_url(original_url)
    except Exception as e:
        logger.error(f"[ROOMS/proxy-stream] Extraction xatosi: {e}")
        raise VideoExtractionException(str(e))

    cdn_url = info.stream_url
    cdn_headers = dict(info.headers)

    # Range header'ni oldinga uzatamiz (seeking uchun muhim)
    range_header = request.headers.get("range")
    if range_header:
        cdn_headers["Range"] = range_header

    logger.info(f"[ROOMS/proxy-stream] CDN ga yo'naltirilmoqda: {cdn_url[:80]}... range={range_header}")

    # CDN'ga ulanib streaming boshlaymiz
    try:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0),
            follow_redirects=True,
        )
        req = client.build_request("GET", cdn_url, headers=cdn_headers)
        cdn_response = await client.send(req, stream=True)
    except Exception as e:
        logger.error(f"[ROOMS/proxy-stream] CDN ulanish xatosi: {e}")
        raise ExternalServiceException("CDN", str(e))

    logger.info(
        f"[ROOMS/proxy-stream] CDN javobi: status={cdn_response.status_code}, "
        f"content-type={cdn_response.headers.get('content-type')}, "
        f"content-length={cdn_response.headers.get('content-length')}"
    )

    async def stream_body():
        try:
            async for chunk in cdn_response.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await cdn_response.aclose()
            await client.aclose()

    # Javob header'larini to'ldirish
    response_headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
    }
    for key in ("content-type", "content-length", "content-range"):
        if key in cdn_response.headers:
            response_headers[key.replace("-", "-")] = cdn_response.headers[key]

    content_type = cdn_response.headers.get("content-type", "video/mp4")

    return StreamingResponse(
        stream_body(),
        status_code=cdn_response.status_code,
        media_type=content_type,
        headers=response_headers,
    )

@router.get("/{room_code}", response_model=RoomOut)
async def get_room(
    room_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"[ROOMS] Xona ma'lumotlari: user={current_user.username}, code={room_code}")
    room = await get_room_by_code(db, room_code)
    if not room:
        logger.warning(f"[ROOMS] Xona topilmadi: code={room_code}")
        raise NotFoundException("Xona")
    logger.info(f"[ROOMS] Xona topildi: video_url={room.video_url}, is_playing={room.is_playing}")
    return RoomOut.model_validate(room)


@router.patch("/{room_code}/video", response_model=RoomOut)
async def set_video(
    room_code: str,
    body: RoomSetVideo,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"[ROOMS] Video o'rnatish: user={current_user.username}, room={room_code}, url={body.video_url}")
    room = await get_room_by_code(db, room_code)
    if not room:
        raise NotFoundException("Xona")
    if room.host_id != current_user.id:
        logger.warning(f"[ROOMS] Ruxsat yo'q: user={current_user.username} host emas!")
        raise ForbiddenException("Faqat xona egasi video o'zgartira oladi")
    room = await update_room_video(db, room, body.video_url)
    logger.info(f"[ROOMS] Video yangilandi: room={room_code}, url={body.video_url}")
    return RoomOut.model_validate(room)


@router.post("/{room_code}/invite", status_code=204)
async def invite_user(
    room_code: str,
    body: InviteBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"[ROOMS] Taklif: user={current_user.username}, room={room_code}, to_user_id={body.to_user_id}")
    room = await get_room_by_code(db, room_code)
    if not room:
        raise NotFoundException("Xona")

    target = await get_user_by_id(db, body.to_user_id)
    if not target:
        raise NotFoundException("Foydalanuvchi")

    if target.fcm_token:
        await send_room_invite(
            fcm_token=target.fcm_token,
            room_code=room.code,
            room_name=room.name,
            inviter_name=current_user.username,
        )
        logger.info(f"[ROOMS] FCM taklif yuborildi: to={target.username}")
    else:
        logger.warning(f"[ROOMS] Foydalanuvchida FCM token yo'q: user={target.username}")
