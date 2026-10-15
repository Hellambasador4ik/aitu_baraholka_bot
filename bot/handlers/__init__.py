from aiogram import Router

from bot.handlers import admin, user


def setup_routers() -> Router:
    root = Router(name="root")
    # Админский роутер первым: кнопки модерации и команды админа
    # обрабатываются до пользовательских хендлеров.
    root.include_routers(admin.router, user.router)
    return root
