import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import texts
from bot.config import Config
from bot.db import (
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_REJECTED,
    USER_ACTIVE,
    USER_BANNED,
    Ad,
    Database,
)
from bot.keyboards import ModerationCb, moderation_kb, reject_reasons_kb
from bot.moderation import notify_user, refresh_cards, send_post

log = logging.getLogger(__name__)
router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery, config: Config) -> bool:
        return event.from_user is not None and event.from_user.id in config.admin_ids


def card_markup(ad: Ad) -> InlineKeyboardMarkup | None:
    """Какие кнопки должны быть под карточкой в текущем статусе объявления."""
    if ad.status == STATUS_NEW:
        return moderation_kb(ad.id)
    if ad.status == STATUS_REJECTED and not ad.reject_reason:
        return reject_reasons_kb(ad.id)
    return None


def post_url(message: Message) -> str | None:
    if message.chat.username:
        return f"https://t.me/{message.chat.username}/{message.message_id}"
    return None


async def already_processed(callback: CallbackQuery, bot: Bot, db: Database, ad_id: int) -> None:
    ad = await db.get_ad(ad_id)
    if ad is None:
        await callback.answer("Объявление не найдено.", show_alert=True)
        return
    # Синхронизируем карточку на случай, если она устарела.
    await refresh_cards(bot, db, ad, card_markup(ad))
    await callback.answer("Это объявление уже обработано другим модератором.", show_alert=True)


# ---------- кнопки модерации ----------


@router.callback_query(ModerationCb.filter(F.action == "approve"), IsAdmin())
async def approve(
    callback: CallbackQuery, callback_data: ModerationCb, bot: Bot, db: Database, config: Config
) -> None:
    ad_id = callback_data.ad_id
    moderator = callback.from_user
    if not await db.claim_ad(ad_id, STATUS_APPROVED, moderator.id, moderator.username):
        await already_processed(callback, bot, db, ad_id)
        return

    ad = await db.get_ad(ad_id)
    try:
        sent = await send_post(bot, config.channel_id, texts.format_ad_post(ad), ad.photos)
    except TelegramAPIError as e:
        log.exception("Не удалось опубликовать объявление #%s", ad_id)
        await db.release_ad(ad_id, STATUS_APPROVED)
        await callback.answer(
            f"❗ Не удалось опубликовать в канал: {e.message}"[:190], show_alert=True
        )
        return

    await db.set_published(ad_id, [m.message_id for m in sent])
    ad = await db.get_ad(ad_id)
    await refresh_cards(bot, db, ad)

    url = post_url(sent[0])
    markup = (
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="👀 Посмотреть пост", url=url)]]
        )
        if url
        else None
    )
    await notify_user(bot, ad.author_id, texts.USER_APPROVED, reply_markup=markup)
    await callback.answer("✅ Опубликовано")


@router.callback_query(ModerationCb.filter(F.action == "reject"), IsAdmin())
async def reject(
    callback: CallbackQuery, callback_data: ModerationCb, bot: Bot, db: Database
) -> None:
    ad_id = callback_data.ad_id
    moderator = callback.from_user
    if not await db.claim_ad(ad_id, STATUS_REJECTED, moderator.id, moderator.username):
        await already_processed(callback, bot, db, ad_id)
        return
    ad = await db.get_ad(ad_id)
    await refresh_cards(bot, db, ad, reject_reasons_kb(ad_id))
    await callback.answer("Выберите причину отклонения")


@router.callback_query(
    ModerationCb.filter((F.action == "reason") & F.reason.in_(texts.REJECT_REASONS)), IsAdmin()
)
async def reject_reason(
    callback: CallbackQuery, callback_data: ModerationCb, bot: Bot, db: Database
) -> None:
    ad_id = callback_data.ad_id
    reason = texts.REJECT_REASONS[callback_data.reason]
    if not await db.set_reject_reason(ad_id, reason):
        await already_processed(callback, bot, db, ad_id)
        return
    ad = await db.get_ad(ad_id)
    await refresh_cards(bot, db, ad)
    await notify_user(bot, ad.author_id, texts.USER_REJECTED.format(reason=reason))
    await callback.answer("🔴 Отклонено")


@router.callback_query(ModerationCb.filter(F.action == "back"), IsAdmin())
async def reject_undo(
    callback: CallbackQuery, callback_data: ModerationCb, bot: Bot, db: Database
) -> None:
    ad_id = callback_data.ad_id
    if not await db.release_ad(ad_id, STATUS_REJECTED):
        await already_processed(callback, bot, db, ad_id)
        return
    ad = await db.get_ad(ad_id)
    await refresh_cards(bot, db, ad, moderation_kb(ad_id))
    await callback.answer("Объявление снова ждёт решения")


@router.callback_query(ModerationCb.filter())
async def not_admin(callback: CallbackQuery) -> None:
    # Посторонние (например, участники чата модерации без прав) — игнорируем.
    await callback.answer(
        "⛔ Модерировать объявления могут только администраторы.", show_alert=True
    )


# ---------- команды админа ----------

ADMIN_HELP = (
    "👑 <b>Команды администратора</b>\n\n"
    "/delete &lt;ID объявления&gt; — удалить опубликованный пост из канала\n"
    "/ban &lt;ID пользователя&gt; — запретить подавать объявления\n"
    "/unban &lt;ID пользователя&gt; — снять запрет\n"
    "/stats — статистика\n"
    "/myid — показать свой ID и ID чата"
)


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    # Доступна всем: помогает заполнить ADMIN_IDS / ADMIN_CHAT_ID при настройке.
    await message.answer(
        f"Ваш ID: <code>{message.from_user.id}</code>\n"
        f"ID этого чата: <code>{message.chat.id}</code>"
    )


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message) -> None:
    await message.answer(ADMIN_HELP)


def parse_id(command: CommandObject) -> int | None:
    try:
        return int((command.args or "").strip().lstrip("#"))
    except ValueError:
        return None


@router.message(Command("delete"), IsAdmin())
async def cmd_delete(
    message: Message, command: CommandObject, bot: Bot, db: Database, config: Config
) -> None:
    ad_id = parse_id(command)
    if ad_id is None:
        await message.answer("Использование: /delete &lt;ID объявления&gt;, например /delete 124")
        return
    ad = await db.get_ad(ad_id)
    if ad is None or ad.status != STATUS_APPROVED or not ad.channel_message_ids:
        await message.answer(f"Объявление #{ad_id} не опубликовано в канале.")
        return
    try:
        await bot.delete_messages(config.channel_id, ad.channel_message_ids)
    except TelegramAPIError as e:
        await message.answer(
            f"❗ Не удалось удалить пост #{ad_id}: {e.message}\n"
            "Проверьте, что у бота есть право удалять сообщения в канале "
            "(Telegram не даёт удалять посты старше 48 часов)."
        )
        return
    await db.mark_deleted(ad_id)
    await refresh_cards(bot, db, await db.get_ad(ad_id))
    await message.answer(f"🗑 Пост #{ad_id} удалён из канала.")


@router.message(Command("ban", "unban"), IsAdmin())
async def cmd_ban(message: Message, command: CommandObject, db: Database) -> None:
    user_id = parse_id(command)
    if user_id is None:
        await message.answer(f"Использование: /{command.command} &lt;ID пользователя&gt;")
        return
    banning = command.command == "ban"
    if not await db.set_user_status(user_id, USER_BANNED if banning else USER_ACTIVE):
        await message.answer("Пользователь не найден (он ещё не запускал бота).")
        return
    await message.answer(
        f"🚫 Пользователь {user_id} заблокирован."
        if banning
        else f"✅ Пользователь {user_id} разблокирован."
    )


@router.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message, db: Database) -> None:
    s = await db.stats()
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: {s.get('users', 0)}\n"
        f"Ждут модерации: {s.get('new', 0)}\n"
        f"Опубликовано: {s.get('approved', 0)}\n"
        f"Отклонено: {s.get('rejected', 0)}\n"
        f"Удалено из канала: {s.get('deleted', 0)}"
    )
