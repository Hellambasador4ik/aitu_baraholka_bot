from dataclasses import dataclass
from html import escape

from bot.db import STATUS_APPROVED, STATUS_DELETED, STATUS_REJECTED, Ad

MAX_TEXT_LENGTH = 800
MAX_CONTACT_LENGTH = 100
MAX_PHOTOS = 4


@dataclass(frozen=True)
class Category:
    button: str  # подпись кнопки
    title: str  # название для карточки админа
    hashtag: str  # хэштег в конце поста в канале


CATEGORIES: dict[str, Category] = {
    "housing": Category("🏢 Жилье/Сожители", "Жилье", "#жилье"),
    "market": Category("👕 Барахолка", "Барахолка", "#барахолка"),
    "services": Category("🛠 Услуги/Вакансии", "Услуги", "#услуги"),
    "other": Category("🎁 Другое", "Другое", "#другое"),
}

REJECT_REASONS: dict[str, str] = {
    "spam": "Спам",
    "offtopic": "Не по теме",
    "forbidden": "Запрещенка",
}

BTN_SUBMIT = "📢 Подать объявление"
BTN_RULES = "📜 Правила канала"
BTN_CANCEL = "❌ Отменить подачу"

WELCOME = (
    "👋 Привет, {name}!\n\n"
    "Это бот барахолки <b>AITU</b>. Здесь можно подать объявление о жилье, "
    "продаже вещей, услугах или вакансиях — после проверки модератором оно "
    "появится в канале.\n\n"
    "Выбери действие в меню ниже 👇"
)

RULES = (
    "📜 <b>Правила канала</b>\n\n"
    "1. Объявления только для студентов и сотрудников AITU.\n"
    "2. Одно объявление — один товар/услуга. Не чаще 1 раза в 10 минут.\n"
    "3. Запрещены: алкоголь, табак, вейпы, наркотики, оружие, "
    "поддельные документы, услуги по написанию работ «под ключ», ставки и казино.\n"
    "4. Без мата, оскорблений и дискриминации.\n"
    "5. Указывайте реальную цену и актуальный контакт.\n"
    "6. Спам и реклама сторонних каналов без согласования — бан.\n\n"
    "Модератор вправе отклонить объявление без объяснения деталей."
)

ASK_CATEGORY = "🗂 <b>Шаг 1/4.</b> Выбери категорию объявления:"
ASK_TEXT = (
    "✍️ <b>Шаг 2/4.</b> Пришли описание объявления одним сообщением.\n\n"
    "Что указать: что предлагаешь или ищешь, цену, состояние, район/корпус и т.п.\n"
    f"Максимум — {MAX_TEXT_LENGTH} символов."
)
TEXT_TOO_LONG = (
    "⚠️ Слишком длинно: {length} символов из {limit}. Сократи текст и пришли снова."
)
TEXT_EXPECTED = "⚠️ Нужно прислать описание текстом."
ASK_PHOTOS = (
    "📷 <b>Шаг 3/4.</b> Пришли фото (одно или альбомом до {limit} шт.) "
    "или нажми «Пропустить фото»."
).format(limit=MAX_PHOTOS)
TOO_MANY_PHOTOS = f"⚠️ Можно прикрепить не больше {MAX_PHOTOS} фото. Пришли альбом заново."
PHOTO_EXPECTED = "⚠️ Пришли фото (не файлом) или нажми «Пропустить фото»."
ASK_CONTACT = (
    "📞 <b>Шаг 4/4.</b> У тебя не указан юзернейм в Telegram, поэтому покупатели не смогут "
    "тебе написать.\n\nНапиши контакт для связи (телефон, WhatsApp, Instagram и т.п.) "
    f"— до {MAX_CONTACT_LENGTH} символов."
)
CONTACT_TOO_LONG = f"⚠️ Контакт слишком длинный (максимум {MAX_CONTACT_LENGTH} символов)."
PREVIEW_HEADER = "👀 <b>Превью твоего объявления:</b>"
SENT_TO_MODERATION = (
    "⏳ Ваше объявление отправлено на модерацию. Обычно это занимает до 15 минут."
)
CANCELLED = "Подача объявления отменена."
RATE_LIMITED = (
    "⏱ Подавать объявления можно не чаще одного раза в {minutes} мин.\n"
    "Попробуй снова через {wait}."
)
BANNED = "🚫 Вы заблокированы и не можете подавать объявления."

USER_APPROVED = "🎉 Ваше объявление успешно опубликовано в канале!"
USER_REJECTED = "⚠️ Ваше объявление отклонено модератором. Причина: {reason}"


def format_wait(seconds: int) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    if minutes and secs:
        return f"{minutes} мин. {secs} сек."
    if minutes:
        return f"{minutes} мин."
    return f"{secs} сек."


def format_post(category: str, text: str, contact: str) -> str:
    """Готовый пост для канала (HTML). Хэштег категории — в конце."""
    cat = CATEGORIES[category]
    return (
        f"<b>{cat.button}</b>\n\n"
        f"{escape(text)}\n\n"
        f"📞 Связь: {escape(contact)}\n\n"
        f"{cat.hashtag}"
    )


def format_ad_post(ad: Ad) -> str:
    return format_post(ad.category, ad.text, ad.contact)


def _mention(user_id: int, username: str | None) -> str:
    if username:
        return f"@{escape(username)}"
    return f'<a href="tg://user?id={user_id}">без юзернейма</a>'


def format_admin_card(ad: Ad) -> str:
    """Карточка объявления для чата модераторов.

    Пока объявление ждёт решения — обычный текст. После решения текст
    «блекнет» (курсив) и добавляется строка со статусом.
    """
    cat = CATEGORIES[ad.category]
    header = "НОВОЕ ОБЪЯВЛЕНИЕ" if ad.status == "new" else "ОБЪЯВЛЕНИЕ"
    lines = [
        f"<b>{header} #{ad.id}</b>",
        f"👤 Автор: {_mention(ad.author_id, ad.author_username)} (ID: <code>{ad.author_id}</code>)",
        f"🗂 Категория: #{cat.title}",
        f"📞 Контакт: {escape(ad.contact)}",
    ]
    if ad.photos:
        lines.append(f"🖼 Фото: {len(ad.photos)} шт. (см. выше)")
    lines += ["", f"Текст: {escape(ad.text)}"]
    body = "\n".join(lines)

    if ad.status == "new":
        return body

    moderator = _mention(ad.moderator_id or 0, ad.moderator_username)
    if ad.status == STATUS_APPROVED:
        status = f"Одобрено админом {moderator} 🟢"
    elif ad.status == STATUS_REJECTED:
        status = "Отклонено 🔴"
        if ad.reject_reason:
            status += f"\nПричина: {escape(ad.reject_reason)} (админ {moderator})"
        else:
            status += "\nВыберите причину отклонения:"
    elif ad.status == STATUS_DELETED:
        status = "Опубликовано, затем удалено из канала 🗑"
    else:
        status = escape(ad.status)
    return f"<i>{body}</i>\n\n<b>{status}</b>"
