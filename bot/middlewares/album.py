import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AlbumMiddleware(BaseMiddleware):
    """Склеивает сообщения одного альбома (MediaGroup) в одно событие.

    Telegram присылает каждое фото альбома отдельным апдейтом. Middleware
    копит их, пока не наступит пауза `latency` секунд, и вызывает хендлер
    один раз — для первого сообщения, передав весь альбом в `data["album"]`.
    Остальные сообщения альбома дальше не обрабатываются.
    """

    def __init__(self, latency: float = 0.6):
        self.latency = latency
        self._albums: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        key = f"{event.chat.id}:{event.media_group_id}"
        if key in self._albums:
            self._albums[key].append(event)
            return None

        self._albums[key] = [event]
        # Ждём, пока поток сообщений альбома не стихнет.
        seen = 0
        while seen != len(self._albums[key]):
            seen = len(self._albums[key])
            await asyncio.sleep(self.latency)

        album = sorted(self._albums.pop(key), key=lambda m: m.message_id)
        data["album"] = album
        return await handler(album[0], data)
