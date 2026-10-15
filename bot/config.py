import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    channel_id: int | str
    admin_chat_id: int | None
    db_path: str
    rate_limit_seconds: int


def _parse_chat_id(value: str) -> int | str:
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        return value if value.startswith("@") else f"@{value}"


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан (см. .env.example)")

    admin_ids = frozenset(
        int(part) for part in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if part
    )
    if not admin_ids:
        raise RuntimeError("ADMIN_IDS не задан: укажите хотя бы одного администратора")

    channel = os.getenv("CHANNEL_ID", "").strip()
    if not channel:
        raise RuntimeError("CHANNEL_ID не задан (например, @aitu_hub)")

    admin_chat = os.getenv("ADMIN_CHAT_ID", "").strip()

    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        channel_id=_parse_chat_id(channel),
        admin_chat_id=int(admin_chat) if admin_chat else None,
        db_path=os.getenv("DB_PATH", "bot.db").strip() or "bot.db",
        rate_limit_seconds=int(os.getenv("RATE_LIMIT_SECONDS", "600")),
    )
