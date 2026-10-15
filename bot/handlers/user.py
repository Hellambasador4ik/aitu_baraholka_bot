import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, User

from bot import texts
from bot.config import Config
from bot.db import USER_BANNED, Database
from bot.keyboards import (
    CategoryCb,
    SkipPhotosCb,
    cancel_menu,
    categories_kb,
    main_menu,
    skip_photos_kb,
)
from bot.moderation import send_post, send_to_moderators
from bot.states import SubmitAd

router = Router(name="user")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")


async def seconds_until_allowed(user_id: int, db: Database, config: Config) -> int:
    """Сколько секунд осталось до следующей подачи (0 — можно подавать)."""
    if user_id in config.admin_ids:
        return 0
    last = await db.last_ad_time(user_id)
    if last is None:
        return 0
    return max(0, last + config.rate_limit_seconds - int(time.time()))


async def check_can_submit(message: Message, user: User, db: Database, config: Config) -> bool:
    status = await db.upsert_user(user.id, user.username)
    if status == USER_BANNED:
        await message.answer(texts.BANNED, reply_markup=main_menu())
        return False
    wait = await seconds_until_allowed(user.id, db, config)
    if wait:
        await message.answer(
            texts.RATE_LIMITED.format(
                minutes=config.rate_limit_seconds // 60, wait=texts.format_wait(wait)
            ),
            reply_markup=main_menu(),
        )
        return False
    return True


# ---------- главное меню ----------


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    await db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        texts.WELCOME.format(name=message.from_user.first_name or "друг"),
        reply_markup=main_menu(),
    )


@router.message(F.text == texts.BTN_RULES)
@router.message(Command("rules"))
async def show_rules(message: Message) -> None:
    await message.answer(texts.RULES)


@router.message(Command("cancel"))
@router.message(F.text == texts.BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.CANCELLED, reply_markup=main_menu())


@router.message(F.text == texts.BTN_SUBMIT)
@router.message(Command("new"))
async def start_submission(
    message: Message, state: FSMContext, db: Database, config: Config
) -> None:
    await state.clear()
    if not await check_can_submit(message, message.from_user, db, config):
        return
    await state.set_state(SubmitAd.category)
    await message.answer(
        "📢 Начинаем подачу объявления. Отменить можно кнопкой внизу.",
        reply_markup=cancel_menu(),
    )
    await message.answer(texts.ASK_CATEGORY, reply_markup=categories_kb())


# ---------- шаг 1: категория ----------


@router.callback_query(SubmitAd.category, CategoryCb.filter(F.code.in_(texts.CATEGORIES)))
async def choose_category(
    callback: CallbackQuery, callback_data: CategoryCb, state: FSMContext
) -> None:
    category = texts.CATEGORIES[callback_data.code]
    await state.update_data(category=callback_data.code)
    await state.set_state(SubmitAd.text)
    await callback.message.edit_text(f"🗂 Категория: <b>{category.button}</b>")
    await callback.message.answer(texts.ASK_TEXT)
    await callback.answer()


@router.callback_query(CategoryCb.filter())
async def stale_category(callback: CallbackQuery) -> None:
    await callback.answer("Эта кнопка уже неактуальна.", show_alert=False)


@router.message(SubmitAd.category)
async def category_expected(message: Message) -> None:
    await message.answer("👆 Выбери категорию кнопкой выше.", reply_markup=categories_kb())


# ---------- шаг 2: текст ----------


@router.message(SubmitAd.text, F.text)
async def receive_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if len(text) > texts.MAX_TEXT_LENGTH:
        await message.answer(
            texts.TEXT_TOO_LONG.format(length=len(text), limit=texts.MAX_TEXT_LENGTH)
        )
        return
    await state.update_data(text=text)
    await state.set_state(SubmitAd.photos)
    await message.answer(texts.ASK_PHOTOS, reply_markup=skip_photos_kb())


@router.message(SubmitAd.text)
async def text_expected(message: Message) -> None:
    await message.answer(texts.TEXT_EXPECTED)


# ---------- шаг 3: фото ----------


@router.message(SubmitAd.photos, F.photo)
async def receive_photos(
    message: Message,
    state: FSMContext,
    bot: Bot,
    db: Database,
    config: Config,
    album: list[Message] | None = None,
) -> None:
    messages = album or [message]
    if any(not m.photo for m in messages):
        await message.answer(texts.PHOTO_EXPECTED, reply_markup=skip_photos_kb())
        return
    if len(messages) > texts.MAX_PHOTOS:
        await message.answer(texts.TOO_MANY_PHOTOS, reply_markup=skip_photos_kb())
        return
    # Берём самый большой размер каждого фото.
    await state.update_data(photos=[m.photo[-1].file_id for m in messages])
    await ask_contact_or_finish(message, message.from_user, state, bot, db, config)


@router.callback_query(SubmitAd.photos, SkipPhotosCb.filter())
async def skip_photos(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    await state.update_data(photos=[])
    await callback.message.edit_text("📷 Без фото.")
    await callback.answer()
    await ask_contact_or_finish(callback.message, callback.from_user, state, bot, db, config)


@router.callback_query(SkipPhotosCb.filter())
async def stale_skip(callback: CallbackQuery) -> None:
    await callback.answer("Эта кнопка уже неактуальна.")


@router.message(SubmitAd.photos)
async def photo_expected(message: Message) -> None:
    await message.answer(texts.PHOTO_EXPECTED, reply_markup=skip_photos_kb())


# ---------- шаг 4: контакт ----------


async def ask_contact_or_finish(
    message: Message, user: User, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    if user.username:
        await state.update_data(contact=f"@{user.username}")
        await finish_submission(message, user, state, bot, db, config)
        return
    await state.set_state(SubmitAd.contact)
    await message.answer(texts.ASK_CONTACT)


@router.message(SubmitAd.contact, F.text)
async def receive_contact(
    message: Message, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    contact = message.text.strip()
    if len(contact) > texts.MAX_CONTACT_LENGTH:
        await message.answer(texts.CONTACT_TOO_LONG)
        return
    await state.update_data(contact=contact)
    await finish_submission(message, message.from_user, state, bot, db, config)


@router.message(SubmitAd.contact)
async def contact_expected(message: Message) -> None:
    await message.answer(texts.ASK_CONTACT)


# ---------- финал ----------


async def finish_submission(
    message: Message, user: User, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    data = await state.get_data()
    await state.clear()

    # Повторная проверка: за время заполнения анкеты пользователь мог
    # подать другое объявление из второй вкладки или получить бан.
    if not await check_can_submit(message, user, db, config):
        return

    ad_id = await db.create_ad(
        author_id=user.id,
        category=data["category"],
        text=data["text"],
        contact=data["contact"],
        photos=data.get("photos", []),
    )

    await message.answer(texts.PREVIEW_HEADER, reply_markup=ReplyKeyboardRemove())
    await send_post(
        bot,
        message.chat.id,
        texts.format_post(data["category"], data["text"], data["contact"]),
        data.get("photos", []),
    )
    await message.answer(texts.SENT_TO_MODERATION, reply_markup=main_menu())

    await send_to_moderators(bot, db, config, ad_id)
