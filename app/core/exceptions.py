"""
Markazlashtirilgan exception ierarxiyasi.
Barcha xatoliklar shu classlardan meros oladi — bu debug qilishni osonlashtiradi.
"""


class AppException(Exception):
    """Barcha ilovaviy xatoliklar uchun asosiy class."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


# ── 4xx Client Errors ────────────────────────────────────────────────────────

class BadRequestException(AppException):
    def __init__(self, message: str = "Noto'g'ri so'rov"):
        super().__init__(400, "BAD_REQUEST", message)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Autentifikatsiya talab qilinadi"):
        super().__init__(401, "UNAUTHORIZED", message)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Ruxsat yo'q"):
        super().__init__(403, "FORBIDDEN", message)


class NotFoundException(AppException):
    def __init__(self, resource: str = "Resurs"):
        super().__init__(404, "NOT_FOUND", f"{resource} topilmadi")


class ConflictException(AppException):
    def __init__(self, message: str = "Bunday ma'lumot allaqachon mavjud"):
        super().__init__(409, "CONFLICT", message)


class ValidationException(AppException):
    def __init__(self, message: str = "Ma'lumotlar noto'g'ri"):
        super().__init__(422, "VALIDATION_ERROR", message)


# ── 5xx Server Errors ────────────────────────────────────────────────────────

class VideoExtractionException(AppException):
    def __init__(self, message: str = "Video URL ni chiqarib bo'lmadi"):
        super().__init__(422, "VIDEO_EXTRACTION_FAILED", message)


class ExternalServiceException(AppException):
    def __init__(self, service: str, message: str = "Xizmat javob bermadi"):
        super().__init__(502, "EXTERNAL_SERVICE_ERROR", f"{service}: {message}")
