from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.texts import BTN_CANCEL, BTN_RULES, BTN_SUBMIT, CATEGORIES, REJECT_REASONS


class CategoryCb(CallbackData, prefix="cat"):
    code: str


class SkipPhotosCb(CallbackData, prefix="skip"):
    pass


class ModerationCb(CallbackData, prefix="mod"):
    action: str  # approve | reject | reason | back
    ad_id: int
    reason: str = ""


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SUBMIT)], [KeyboardButton(text=BTN_RULES)]],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


def categories_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=cat.button, callback_data=CategoryCb(code=code).pack())
        for code, cat in CATEGORIES.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])


def skip_photos_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏩ Пропустить фото", callback_data=SkipPhotosCb().pack())]
        ]
    )


def moderation_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить и опубликовать",
                    callback_data=ModerationCb(action="approve", ad_id=ad_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=ModerationCb(action="reject", ad_id=ad_id).pack(),
                )
            ],
        ]
    )


def reject_reasons_kb(ad_id: int) -> InlineKeyboardMarkup:
    reasons = [
        InlineKeyboardButton(
            text=title,
            callback_data=ModerationCb(action="reason", ad_id=ad_id, reason=code).pack(),
        )
        for code, title in REJECT_REASONS.items()
    ]
    back = InlineKeyboardButton(
        text="↩️ Отмена (вернуть на модерацию)",
        callback_data=ModerationCb(action="back", ad_id=ad_id).pack(),
    )
    return InlineKeyboardMarkup(inline_keyboard=[reasons, [back]])
