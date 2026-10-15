import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, Message, ReplyParameters

from bot.config import Config
from bot.db import Ad, Database
from bot.keyboards import moderation_kb
from bot.texts import format_admin_card

log = logging.getLogger(__name__)


async def send_post(
    bot: Bot, chat_id: int | str, text: str, photos: list[str]
) -> list[Message]:
    """Отправляет пост: текстом, фото с подписью или альбомом с подписью у первого фото."""
    if not photos:
        return [await bot.send_message(chat_id, text)]
    if len(photos) == 1:
        return [await bot.send_photo(chat_id, photos[0], caption=text)]
    media = [
        InputMediaPhoto(media=file_id, caption=text if i == 0 else None)
        for i, file_id in enumerate(photos)
    ]
    return await bot.send_media_group(chat_id, media)


def moderation_targets(config: Config) -> list[int]:
    if config.admin_chat_id is not None:
        return [config.admin_chat_id]
    return sorted(config.admin_ids)


async def send_to_moderators(bot: Bot, db: Database, config: Config, ad_id: int) -> int:
    """Рассылает карточку объявления модераторам. Возвращает число доставленных карточек."""
    ad = await db.get_ad(ad_id)
    if ad is None:
        return 0

    delivered = 0
    for chat_id in moderation_targets(config):
        try:
            reply_params = None
            if ad.photos:
                if len(ad.photos) == 1:
                    sent = [await bot.send_photo(chat_id, ad.photos[0])]
                else:
                    sent = await bot.send_media_group(
                        chat_id, [InputMediaPhoto(media=p) for p in ad.photos]
                    )
                reply_params = ReplyParameters(message_id=sent[0].message_id)
            card = await bot.send_message(
                chat_id,
                format_admin_card(ad),
                reply_markup=moderation_kb(ad.id),
                reply_parameters=reply_params,
            )
        except TelegramAPIError as e:
            # Например, админ ещё ни разу не запускал бота.
            log.warning("Не удалось отправить карточку #%s в чат %s: %s", ad.id, chat_id, e)
            continue
        await db.add_card(ad.id, chat_id, card.message_id)
        delivered += 1

    if not delivered:
        log.error("Карточка #%s не доставлена ни одному модератору!", ad.id)
    return delivered


async def refresh_cards(
    bot: Bot, db: Database, ad: Ad, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Перерисовывает карточку объявления во всех чатах модераторов."""
    text = format_admin_card(ad)
    for chat_id, message_id in await db.get_cards(ad.id):
        try:
            await bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                log.warning("Не удалось обновить карточку #%s в %s: %s", ad.id, chat_id, e)
        except TelegramAPIError as e:
            log.warning("Не удалось обновить карточку #%s в %s: %s", ad.id, chat_id, e)


async def notify_user(bot: Bot, user_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except TelegramAPIError as e:
        # Пользователь заблокировал бота и т.п. — это не должно ломать модерацию.
        log.info("Не удалось уведомить пользователя %s: %s", user_id, e)
        return False
