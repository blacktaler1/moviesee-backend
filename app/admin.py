from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.models.user import User
from app.models.room import Room, Message
from app.config import settings

class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
            request.session.update({"token": "admin-token"})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        if not token:
            return False
        return True

authentication_backend = AdminAuth(secret_key=settings.SECRET_KEY)

class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.email, User.created_at]
    column_searchable_list = [User.username, User.email]
    column_sortable_list = [User.id, User.created_at]
    icon = "fa-solid fa-user"
    name = "Foydalanuvchi"
    name_plural = "Foydalanuvchilar"

class RoomAdmin(ModelView, model=Room):
    column_list = [Room.id, Room.code, Room.name, Room.is_playing, Room.created_at]
    column_searchable_list = [Room.code, Room.name]
    column_sortable_list = [Room.id, Room.created_at]
    icon = "fa-solid fa-door-open"
    name = "Xona"
    name_plural = "Xonalar"

class MessageAdmin(ModelView, model=Message):
    column_list = [Message.id, Message.room_id, Message.user_id, Message.text, Message.created_at]
    column_searchable_list = [Message.text]
    column_sortable_list = [Message.id, Message.created_at]
    icon = "fa-solid fa-message"
    name = "Xabar"
    name_plural = "Xabarlar"

def setup_admin(app, engine):
    admin = Admin(app, engine, authentication_backend=authentication_backend)
    admin.add_view(UserAdmin)
    admin.add_view(RoomAdmin)
    admin.add_view(MessageAdmin)
    return admin
