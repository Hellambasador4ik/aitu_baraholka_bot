import itertools
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    EditMessageText,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User

from bot.config import Config
from bot.db import Database
from bot.handlers import admin, setup_routers, user
from bot.middlewares import AlbumMiddleware

ADMIN_ID = 1
ADMIN2_ID = 2
CHANNEL = "@aitu_hub"
CHANNEL_CHAT = Chat(id=-1001234567890, type="channel", username="aitu_hub")


class FakeSession(BaseSession):
    """Сессия, которая вместо Telegram API записывает вызовы и отдаёт правдоподобные ответы."""

    def __init__(self):
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self._ids = itertools.count(1000)

    def _chat(self, chat_id) -> Chat:
        if chat_id == CHANNEL:
            return CHANNEL_CHAT
        return Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup")

    def _message(self, chat_id, **kwargs) -> Message:
        return Message(
            message_id=next(self._ids), date=datetime.now(), chat=self._chat(chat_id), **kwargs
        )

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return self._message(method.chat_id, text=method.text)
        if isinstance(method, SendPhoto):
            return self._message(method.chat_id, caption=method.caption)
        if isinstance(method, SendMediaGroup):
            return [self._message(method.chat_id) for _ in method.media]
        if isinstance(method, EditMessageText):
            return True
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self):
        pass

    def of(self, method_type) -> list:
        return [r for r in self.requests if isinstance(r, method_type)]


class Env:
    def __init__(self, bot: Bot, dp: Dispatcher, db: Database, config: Config):
        self.bot, self.dp, self.db, self.config = bot, dp, db, config
        self.session: FakeSession = bot.session
        self._ids = itertools.count(1)

    # --- фабрики апдейтов ---

    def user(self, user_id: int, username: str | None = "student") -> User:
        return User(id=user_id, is_bot=False, first_name="Test", username=username)

    def message(self, user: User, text: str | None = None, **kwargs) -> Message:
        return Message(
            message_id=next(self._ids),
            date=datetime.now(),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            text=text,
            **kwargs,
        )

    def photo_message(self, user: User, file_id: str, media_group_id: str | None = None):
        return self.message(
            user,
            photo=[PhotoSize(file_id=file_id, file_unique_id=file_id, width=100, height=100)],
            media_group_id=media_group_id,
        )

    async def send(self, user: User, text: str | None = None, **kwargs) -> None:
        await self.feed(self.message(user, text, **kwargs))

    async def feed(self, message: Message) -> None:
        await self.dp.feed_update(self.bot, Update(update_id=next(self._ids), message=message))

    async def click(self, user: User, data: str, chat_id: int | None = None) -> None:
        chat_id = chat_id if chat_id is not None else user.id
        msg = Message(
            message_id=next(self._ids),
            date=datetime.now(),
            chat=Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup"),
            text="card",
        )
        cb = CallbackQuery(
            id=str(next(self._ids)), from_user=user, chat_instance="x", message=msg, data=data
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(self._ids), callback_query=cb))

    # --- выборки отправленного ---

    def texts_to(self, chat_id) -> list[str]:
        return [r.text for r in self.session.of(SendMessage) if r.chat_id == chat_id]

    def clear(self) -> None:
        self.session.requests.clear()


@pytest.fixture
async def env(tmp_path):
    config = Config(
        bot_token="42:TEST",
        admin_ids=frozenset({ADMIN_ID, ADMIN2_ID}),
        channel_id=CHANNEL,
        admin_chat_id=None,
        db_path=str(tmp_path / "test.db"),
        rate_limit_seconds=600,
    )
    db = Database(config.db_path)
    await db.connect()
    bot = Bot(
        token=config.bot_token,
        session=FakeSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage(), config=config, db=db)
    dp.message.outer_middleware(AlbumMiddleware(latency=0.05))
    dp.include_router(setup_routers())
    yield Env(bot, dp, db, config)
    await db.close()
    # Роутеры — модульные синглтоны; отвязываем их, чтобы следующий тест
    # мог собрать новый Dispatcher.
    for router in (admin.router, user.router):
        router._parent_router = None
