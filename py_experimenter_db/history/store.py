"""SQLite-backed store for SQL query history, saved queries, chat sessions, and scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sql_text TEXT NOT NULL,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    row_count INTEGER,
    duration_ms INTEGER,
    error TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sql_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mental_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS script_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class HistoryEntry:
    id: int
    sql_text: str
    executed_at: str
    row_count: int | None
    duration_ms: int | None
    error: str | None


@dataclass
class SavedQuery:
    id: int
    name: str
    sql_text: str
    created_at: str
    updated_at: str


@dataclass
class ChatSession:
    id: int
    name: str
    created_at: str
    updated_at: str


@dataclass
class ChatMessage:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


@dataclass
class ScriptMeta:
    id: int
    name: str
    created_at: str
    updated_at: str


@dataclass
class ScriptVersion:
    id: int
    script_id: int
    content: str
    created_at: str


class QueryHistoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Run each DDL statement individually so a failure in one doesn't
        # abort the rest, and so commits are guaranteed per statement.
        statements = [s.strip() for s in _SCHEMA.split(";") if s.strip()]
        async with aiosqlite.connect(self.db_path) as db:
            for stmt in statements:
                await db.execute(stmt)
            await db.commit()

    async def add_to_history(
        self,
        sql_text: str,
        row_count: int | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO query_history (sql_text, row_count, duration_ms, error) VALUES (?, ?, ?, ?)",
                (sql_text, row_count, duration_ms, error),
            )
            await db.commit()

    async def get_history(self, limit: int = 50) -> list[HistoryEntry]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, sql_text, executed_at, row_count, duration_ms, error "
                "FROM query_history ORDER BY executed_at DESC LIMIT ?",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            HistoryEntry(
                id=r["id"],
                sql_text=r["sql_text"],
                executed_at=r["executed_at"],
                row_count=r["row_count"],
                duration_ms=r["duration_ms"],
                error=r["error"],
            )
            for r in rows
        ]

    async def save_query(self, name: str, sql_text: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO saved_queries (name, sql_text, created_at, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET sql_text = excluded.sql_text, updated_at = excluded.updated_at""",
                (name, sql_text, now, now),
            )
            await db.commit()

    async def get_saved_queries(self) -> list[SavedQuery]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, sql_text, created_at, updated_at FROM saved_queries ORDER BY name"
            ) as cur:
                rows = await cur.fetchall()
        return [
            SavedQuery(
                id=r["id"],
                name=r["name"],
                sql_text=r["sql_text"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def delete_saved_query(self, query_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
            await db.commit()

    async def get_saved_query(self, query_id: int) -> SavedQuery | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, sql_text, created_at, updated_at FROM saved_queries WHERE id = ?",
                (query_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return SavedQuery(
            id=row["id"],
            name=row["name"],
            sql_text=row["sql_text"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    async def get_all_settings(self) -> dict[str, str]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT key, value FROM settings") as cur:
                rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            await db.commit()

    async def set_settings(self, pairs: dict[str, str]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                list(pairs.items()),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Chat sessions
    # ------------------------------------------------------------------

    async def create_session(self, name: str) -> ChatSession:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO chat_sessions (name, created_at, updated_at) VALUES (?, ?, ?)",
                (name, now, now),
            )
            await db.commit()
            session_id = cur.lastrowid
        return ChatSession(id=session_id, name=name, created_at=now, updated_at=now)

    async def get_sessions(self) -> list[ChatSession]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [ChatSession(id=r["id"], name=r["name"], created_at=r["created_at"], updated_at=r["updated_at"]) for r in rows]

    async def rename_session(self, session_id: int, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE chat_sessions SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, session_id),
            )
            await db.commit()

    async def delete_session(self, session_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            await db.commit()

    async def touch_session(self, session_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id)
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Chat messages
    # ------------------------------------------------------------------

    async def append_message(self, session_id: int, role: str, content: str) -> ChatMessage:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            await db.commit()
            msg_id = cur.lastrowid
        return ChatMessage(id=msg_id, session_id=session_id, role=role, content=content, created_at=now)

    async def get_messages(self, session_id: int) -> list[ChatMessage]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, session_id, role, content, created_at FROM chat_messages "
                "WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            ChatMessage(id=r["id"], session_id=r["session_id"], role=r["role"],
                        content=r["content"], created_at=r["created_at"])
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Mental state
    # ------------------------------------------------------------------

    async def get_mental_state(self) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT content FROM mental_state WHERE id = 1") as cur:
                row = await cur.fetchone()
        return row["content"] if row else ""

    async def set_mental_state(self, content: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO mental_state (id, content, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
                (content, now),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------

    async def get_scripts(self) -> list[ScriptMeta]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, created_at, updated_at FROM scripts ORDER BY updated_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [ScriptMeta(id=r["id"], name=r["name"], created_at=r["created_at"], updated_at=r["updated_at"]) for r in rows]

    async def create_script(self, name: str, content: str) -> ScriptMeta:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO scripts (name, created_at, updated_at) VALUES (?, ?, ?)",
                (name, now, now),
            )
            script_id = cur.lastrowid
            await db.execute(
                "INSERT INTO script_versions (script_id, content, created_at) VALUES (?, ?, ?)",
                (script_id, content, now),
            )
            await db.commit()
        return ScriptMeta(id=script_id, name=name, created_at=now, updated_at=now)

    async def save_script_version(self, script_id: int, content: str) -> ScriptVersion:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO script_versions (script_id, content, created_at) VALUES (?, ?, ?)",
                (script_id, content, now),
            )
            await db.execute(
                "UPDATE scripts SET updated_at = ? WHERE id = ?", (now, script_id)
            )
            await db.commit()
            ver_id = cur.lastrowid
        return ScriptVersion(id=ver_id, script_id=script_id, content=content, created_at=now)

    async def get_script_latest(self, script_id: int) -> ScriptVersion | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, script_id, content, created_at FROM script_versions "
                "WHERE script_id = ? ORDER BY created_at DESC LIMIT 1",
                (script_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return ScriptVersion(id=row["id"], script_id=row["script_id"], content=row["content"], created_at=row["created_at"])

    async def get_script_versions(self, script_id: int) -> list[ScriptVersion]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, script_id, content, created_at FROM script_versions "
                "WHERE script_id = ? ORDER BY created_at DESC",
                (script_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [ScriptVersion(id=r["id"], script_id=r["script_id"], content=r["content"], created_at=r["created_at"]) for r in rows]

    async def rename_script(self, script_id: int, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE scripts SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, script_id),
            )
            await db.commit()

    async def delete_script(self, script_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
            await db.commit()
