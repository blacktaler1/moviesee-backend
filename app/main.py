import logging
import time as time_module
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, init_db
from app.api import auth, rooms
from app.websocket.events import handle_websocket
from app.services.auth import decode_token, get_user_by_id
from app.core.exceptions import AppException

# ── Logging sozlash ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("moviesee")

# Shovqinli tashqi kutubxona loglarini o'chiramiz
for _noisy in ("aiosqlite", "sqlalchemy.engine", "httpcore", "httpx", "hpack"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

app = FastAPI(title="MovieSee API", version="1.0.0")


# ── Global Exception Handlers ────────────────────────────────────
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Barcha ilovaviy xatoliklar uchun yagona handler."""
    req_id = getattr(request.state, "request_id", "-")
    logger.warning(
        f"[{exc.code}] {request.method} {request.url.path}"
        f" | status={exc.status_code} | message={exc.message}"
        f" | req_id={req_id}"
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic validatsiya xatoliklari uchun handler."""
    req_id = getattr(request.state, "request_id", "-")
    errors = [
        {"field": ".".join(str(l) for l in e["loc"][1:]), "message": e["msg"]}
        for e in exc.errors()
    ]
    logger.warning(
        f"[VALIDATION_ERROR] {request.method} {request.url.path}"
        f" | errors={errors} | req_id={req_id}"
    )
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Ma'lumotlar noto'g'ri", "fields": errors}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Kutilmagan xatoliklar uchun — stack trace bilan log qilinadi."""
    req_id = getattr(request.state, "request_id", "-")
    logger.error(
        f"[UNHANDLED_ERROR] {request.method} {request.url.path}"
        f" | req_id={req_id} | error={exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_SERVER_ERROR", "message": "Server ichki xatosi yuz berdi"}},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response logger middleware ──────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    request.state.request_id = req_id
    start = time_module.time()
    client = request.client.host if request.client else "unknown"

    # GET/HEAD so'rovlarda body bo'lmaydi — o'qimaymiz.
    # StreamingResponse (proxy-stream) uchun juda muhim: aks holda
    # Starlette disconnect detection bilan to'qnashib "Unexpected message: http.request" xatosi chiqadi.
    if request.method in ("GET", "HEAD"):
        logger.info(f"[REQ] {req_id} {request.method} {request.url.path} | client={client}")
        response = await call_next(request)
    else:
        body_bytes = await request.body()
        body_log = body_bytes.decode("utf-8", errors="replace")[:300]
        logger.info(f"[REQ] {req_id} {request.method} {request.url.path} | client={client} | body={body_log}")

        # Stateful receive: body bir martа qaytariladi, keyin disconnect simulyatsiya qilinadi.
        # Bu Starlette BaseHTTPMiddleware bilan to'g'ri ishlaydi.
        _body_sent = False

        async def receive():
            nonlocal _body_sent
            if not _body_sent:
                _body_sent = True
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            return {"type": "http.disconnect"}

        request._receive = receive
        response = await call_next(request)

    elapsed = (time_module.time() - start) * 1000
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        level,
        f"[RES] {req_id} {request.method} {request.url.path}"
        f" | status={response.status_code} | took={elapsed:.1f}ms",
    )
    return response


app.include_router(auth.router)
app.include_router(rooms.router)


@app.on_event("startup")
async def startup():
    logger.info("=== MovieSee Backend ishga tushmoqda ===")
    logger.info(f"DATABASE_URL: {settings.DATABASE_URL}")
    logger.info(f"ALLOWED_ORIGINS: {settings.ALLOWED_ORIGINS}")
    await init_db()
    logger.info("=== Ma'lumotlar bazasi tayyor ===")


@app.get("/health")
async def health():
    logger.info("[HEALTH] Health check so'rovi")
    return {"status": "ok"}


@app.websocket("/ws/{room_code}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_code: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"[WS] Yangi ulanish so'rovi: room={room_code}, client={client_host}")

    # Token tekshirish
    payload = decode_token(token)
    if not payload:
        logger.warning(f"[WS] Token yaroqsiz! room={room_code}, client={client_host}")
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = payload.get("sub")
    logger.info(f"[WS] Token to'g'ri, user_id={user_id}, room={room_code}")

    user = await get_user_by_id(db, int(user_id))
    if not user:
        logger.warning(f"[WS] Foydalanuvchi topilmadi! user_id={user_id}")
        await websocket.close(code=4001, reason="User not found")
        return

    logger.info(f"[WS] Foydalanuvchi ulandi: username={user.username}, room={room_code}")
    await handle_websocket(websocket, room_code, user, db)
    logger.info(f"[WS] Foydalanuvchi chiqdi: username={user.username}, room={room_code}")
