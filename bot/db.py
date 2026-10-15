import json
import time
from dataclasses import dataclass

import aiosqlite

STATUS_NEW = "new"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_DELETED = "deleted"

USER_ACTIVE = "active"
USER_BANNED = "banned"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    registered_at INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS advertisements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id           INTEGER NOT NULL REFERENCES users(id),
    category            TEXT NOT NULL,
    text                TEXT NOT NULL,
    contact             TEXT NOT NULL,
    photos              TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'new',
    reject_reason       TEXT,
    moderator_id        INTEGER,
    moderator_username  TEXT,
    channel_message_id  INTEGER,
    channel_message_ids TEXT NOT NULL DEFAULT '[]',
    created_at          INTEGER NOT NULL,
    moderated_at        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_ads_author_created ON advertisements(author_id, created_at);

-- Карточки модерации, разосланные админам (по одной на чат), чтобы
-- после решения одного админа обновить карточки у всех остальных.
CREATE TABLE IF NOT EXISTS moderation_cards (
    ad_id      INTEGER NOT NULL REFERENCES advertisements(id),
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (ad_id, chat_id)
);
"""


@dataclass
class Ad:
    id: int
    author_id: int
    author_username: str | None
    category: str
    text: str
    contact: str
    photos: list[str]
    status: str
    reject_reason: str | None
    moderator_id: int | None
    moderator_username: str | None
    channel_message_ids: list[int]
    created_at: int


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    # ---------- users ----------

    async def upsert_user(self, user_id: int, username: str | None) -> str:
        """Регистрирует пользователя (или обновляет юзернейм) и возвращает его статус."""
        await self.conn.execute(
            """
            INSERT INTO users (id, username, registered_at) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET username = excluded.username
            """,
            (user_id, username, int(time.time())),
        )
        await self.conn.commit()
        return await self.get_user_status(user_id) or USER_ACTIVE

    async def get_user_status(self, user_id: int) -> str | None:
        async with self.conn.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return row["status"] if row else None

    async def set_user_status(self, user_id: int, status: str) -> bool:
        cur = await self.conn.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status, user_id)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ---------- advertisements ----------

    async def last_ad_time(self, author_id: int) -> int | None:
        async with self.conn.execute(
            "SELECT MAX(created_at) AS t FROM advertisements WHERE author_id = ?", (author_id,)
        ) as cur:
            row = await cur.fetchone()
        return row["t"] if row else None

    async def create_ad(
        self, author_id: int, category: str, text: str, contact: str, photos: list[str]
    ) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO advertisements (author_id, category, text, contact, photos, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (author_id, category, text, contact, json.dumps(photos), int(time.time())),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_ad(self, ad_id: int) -> Ad | None:
        async with self.conn.execute(
            """
            SELECT a.*, u.username AS author_username
            FROM advertisements a LEFT JOIN users u ON u.id = a.author_id
            WHERE a.id = ?
            """,
            (ad_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return Ad(
            id=row["id"],
            author_id=row["author_id"],
            author_username=row["author_username"],
            category=row["category"],
            text=row["text"],
            contact=row["contact"],
            photos=json.loads(row["photos"]),
            status=row["status"],
            reject_reason=row["reject_reason"],
            moderator_id=row["moderator_id"],
            moderator_username=row["moderator_username"],
            channel_message_ids=json.loads(row["channel_message_ids"]),
            created_at=row["created_at"],
        )

    async def claim_ad(
        self, ad_id: int, new_status: str, moderator_id: int, moderator_username: str | None
    ) -> bool:
        """Атомарно переводит объявление из статуса `new` в `new_status`.

        Возвращает False, если объявление уже обработал другой админ —
        это защищает от двойной публикации при одновременных нажатиях.
        """
        cur = await self.conn.execute(
            """
            UPDATE advertisements
            SET status = ?, moderator_id = ?, moderator_username = ?, moderated_at = ?
            WHERE id = ? AND status = ?
            """,
            (new_status, moderator_id, moderator_username, int(time.time()), ad_id, STATUS_NEW),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def release_ad(self, ad_id: int, from_status: str) -> bool:
        """Возвращает объявление в очередь модерации (откат claim_ad)."""
        cur = await self.conn.execute(
            """
            UPDATE advertisements
            SET status = ?, moderator_id = NULL, moderator_username = NULL,
                moderated_at = NULL, reject_reason = NULL
            WHERE id = ? AND status = ? AND reject_reason IS NULL
            """,
            (STATUS_NEW, ad_id, from_status),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def set_reject_reason(self, ad_id: int, reason: str) -> bool:
        cur = await self.conn.execute(
            """
            UPDATE advertisements SET reject_reason = ?
            WHERE id = ? AND status = ? AND reject_reason IS NULL
            """,
            (reason, ad_id, STATUS_REJECTED),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def set_published(self, ad_id: int, message_ids: list[int]) -> None:
        await self.conn.execute(
            """
            UPDATE advertisements SET channel_message_id = ?, channel_message_ids = ?
            WHERE id = ?
            """,
            (message_ids[0] if message_ids else None, json.dumps(message_ids), ad_id),
        )
        await self.conn.commit()

    async def mark_deleted(self, ad_id: int) -> None:
        await self.conn.execute(
            "UPDATE advertisements SET status = ? WHERE id = ?", (STATUS_DELETED, ad_id)
        )
        await self.conn.commit()

    async def stats(self) -> dict[str, int]:
        result = {"users": 0}
        async with self.conn.execute("SELECT COUNT(*) AS c FROM users") as cur:
            result["users"] = (await cur.fetchone())["c"]
        async with self.conn.execute(
            "SELECT status, COUNT(*) AS c FROM advertisements GROUP BY status"
        ) as cur:
            for row in await cur.fetchall():
                result[row["status"]] = row["c"]
        return result

    # ---------- moderation cards ----------

    async def add_card(self, ad_id: int, chat_id: int, message_id: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO moderation_cards (ad_id, chat_id, message_id) VALUES (?, ?, ?)",
            (ad_id, chat_id, message_id),
        )
        await self.conn.commit()

    async def get_cards(self, ad_id: int) -> list[tuple[int, int]]:
        async with self.conn.execute(
            "SELECT chat_id, message_id FROM moderation_cards WHERE ad_id = ?", (ad_id,)
        ) as cur:
            return [(row["chat_id"], row["message_id"]) for row in await cur.fetchall()]
