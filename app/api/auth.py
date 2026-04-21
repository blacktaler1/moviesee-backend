import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.user import UserRegister, UserLogin, UserOut, TokenOut
from app.services.auth import (
    get_user_by_email,
    register_user,
    verify_password,
    create_access_token,
)
from app.api.deps import get_current_user
from app.models.user import User
from app.core.exceptions import ConflictException, UnauthorizedException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class FcmTokenBody(BaseModel):
    fcm_token: str


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    logger.info(f"[AUTH] Ro'yxatdan o'tish: username={body.username}, email={body.email}")
    existing = await get_user_by_email(db, body.email)
    if existing:
        logger.warning(f"[AUTH] Email allaqachon ro'yxatdan o'tgan: {body.email}")
        raise ConflictException("Bu email allaqachon ro'yxatdan o'tgan")

    user = await register_user(db, body.username, body.email, body.password)
    token = create_access_token({"sub": str(user.id)})
    logger.info(f"[AUTH] Yangi foydalanuvchi yaratildi: id={user.id}, username={user.username}")
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)):
    logger.info(f"[AUTH] Kirish urinishi: email={body.email}")
    user = await get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user.hashed_password):
        logger.warning(f"[AUTH] Noto'g'ri login/parol: email={body.email}")
        raise UnauthorizedException("Email yoki parol noto'g'ri")

    token = create_access_token({"sub": str(user.id)})
    logger.info(f"[AUTH] Muvaffaqiyatli kirish: id={user.id}, username={user.username}")
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    logger.info(f"[AUTH] /me: user={current_user.username}, id={current_user.id}")
    return UserOut.model_validate(current_user)


@router.post("/fcm-token", status_code=204)
async def save_fcm_token(
    body: FcmTokenBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"[AUTH] FCM token saqlash: user={current_user.username}, token={body.fcm_token[:20]}...")
    current_user.fcm_token = body.fcm_token
    await db.commit()
    logger.info(f"[AUTH] FCM token saqlandi: user={current_user.username}")
