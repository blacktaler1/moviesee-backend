"""
Firebase Cloud Messaging V1 API orqali push notification yuborish.
firebase-admin SDK ishlatiladi (Legacy API emas).

Sozlash:
  1. Firebase Console → Project Settings → Service accounts
  2. "Generate new private key" → JSON yuklab oling
  3. Faylni  backend/firebase-credentials.json  ga saqlang
  4. Yoki FIREBASE_CREDENTIALS_JSON muhit o'zgaruvchisiga JSON mazmunini bering
"""
import os
import json
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    _FIREBASE_AVAILABLE = True
except ImportError:
    _FIREBASE_AVAILABLE = False
    logger.warning("firebase-admin o'rnatilmagan. pip install firebase-admin")


@lru_cache(maxsize=1)
def _get_firebase_app():
    """Firebase App'ni bir marta ishga tushiradi (lazy init)."""
    if not _FIREBASE_AVAILABLE:
        return None

    # Usul 1: JSON fayl orqali
    # "firebase-credentials.json" yoki "*firebase-adminsdk*.json" nomli faylni qidirish
    backend_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "../.."))
    cred_file = os.path.join(backend_dir, "firebase-credentials.json")

    if not os.path.exists(cred_file):
        # Firebase Console dan yuklab olingan standart nom formatini qidirish
        import glob
        candidates = glob.glob(os.path.join(backend_dir, "*firebase-adminsdk*.json"))
        if candidates:
            cred_file = candidates[0]
            logger.info(f"Firebase credentials topildi: {os.path.basename(cred_file)}")

    # Usul 2: Muhit o'zgaruvchisi orqali (Render/Railway deploy uchun qulay)
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

    try:
        if cred_json:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
        elif os.path.exists(cred_file):
            cred = credentials.Certificate(cred_file)
        else:
            logger.warning(
                "Firebase credentials topilmadi. "
                "firebase-credentials.json qo'ying yoki "
                "FIREBASE_CREDENTIALS_JSON muhit o'zgaruvchisini bering."
            )
            return None

        if not firebase_admin._apps:
            return firebase_admin.initialize_app(cred)
        return firebase_admin.get_app()
    except Exception as e:
        logger.error(f"Firebase init xatosi: {e}")
        return None


async def send_room_invite(
    fcm_token: str,
    room_code: str,
    room_name: str,
    inviter_name: str,
) -> bool:
    """
    Xonaga taklif push notification'ini yuborish.
    Firebase Admin SDK (V1 API) ishlatadi.
    """
    app = _get_firebase_app()
    if app is None:
        logger.warning("Firebase sozlanmagan — notification yuborilmadi")
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"{inviter_name} sizni taklif qildi",
                body=f"'{room_name}' xonasida birgalikda tomosha qilaylik!",
            ),
            data={
                "type": "room_invite",
                "room_code": room_code,
                "room_name": room_name,
                "inviter": inviter_name,
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="moviesee_invites",
                    sound="default",
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound="default",
                        badge=1,
                    )
                )
            ),
            token=fcm_token,
        )
        messaging.send(message)
        return True
    except messaging.UnregisteredError:
        logger.info(f"FCM token eskirgan: {fcm_token[:20]}...")
        return False
    except Exception as e:
        logger.error(f"FCM yuborishda xato: {e}")
        return False
