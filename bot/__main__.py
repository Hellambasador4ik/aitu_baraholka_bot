import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import load_config
from bot.db import Database
from bot.handlers import setup_routers
from bot.middlewares import AlbumMiddleware


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = load_config()

    db = Database(config.db_path)
    await db.connect()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher(storage=MemoryStorage(), config=config, db=db)
    dp.message.outer_middleware(AlbumMiddleware())
    dp.include_router(setup_routers())

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="new", description="Подать объявление"),
            BotCommand(command="rules", description="Правила канала"),
            BotCommand(command="cancel", description="Отменить подачу"),
        ]
    )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
