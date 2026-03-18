"""Database backend abstraction supporting both MySQL (aiomysql) and SQLite (aiosqlite)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, TYPE_CHECKING

import aiomysql
import aiosqlite

if TYPE_CHECKING:
    from py_experimenter_db.config import CredentialsConfig, ExperimenterConfig


class _Cursor:
    """Unified async cursor — adapts aiosqlite to match enough of the aiomysql DictCursor API."""

    def __init__(self, cur: Any, is_sqlite: bool) -> None:
        self._cur = cur
        self._is_sqlite = is_sqlite

    @staticmethod
    def _adapt_sql(sql: str) -> str:
        """Convert %s placeholders to ? for SQLite."""
        return sql.replace("%s", "?")

    async def execute(self, sql: str, params: Any = None) -> None:
        if self._is_sqlite:
            await self._cur.execute(self._adapt_sql(sql), params or ())
        else:
            await self._cur.execute(sql, params)

    async def fetchone(self) -> dict[str, Any] | None:
        row = await self._cur.fetchone()
        if row is None:
            return None
        return dict(row) if self._is_sqlite else row

    async def fetchall(self) -> list[dict[str, Any]]:
        rows = await self._cur.fetchall()
        return [dict(r) for r in rows] if self._is_sqlite else list(rows)

    async def fetchmany(self, size: int) -> list[Any]:
        rows = await self._cur.fetchmany(size)
        return [dict(r) for r in rows] if self._is_sqlite else list(rows)

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self) -> Any:
        return self._cur.description

    async def __aenter__(self) -> "_Cursor":
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._is_sqlite:
            await self._cur.close()
        else:
            self._cur.close()


class _Conn:
    """Unified connection wrapper."""

    def __init__(self, raw: Any, is_sqlite: bool) -> None:
        self._raw = raw
        self._is_sqlite = is_sqlite

    def cursor(self, *args: Any) -> Any:
        # Returns an async context manager (_Cursor supports __aenter__/__aexit__)
        if self._is_sqlite:
            return _SqliteCursorCtx(self._raw, is_sqlite=True)
        return _MySQLCursorCtx(self._raw, *args)


class _SqliteCursorCtx:
    def __init__(self, conn: aiosqlite.Connection, *, is_sqlite: bool) -> None:
        self._conn = conn
        self._is_sqlite = is_sqlite
        self._cur: aiosqlite.Cursor | None = None

    async def __aenter__(self) -> _Cursor:
        self._cur = await self._conn.cursor()
        return _Cursor(self._cur, is_sqlite=True)

    async def __aexit__(self, *args: Any) -> None:
        if self._cur:
            await self._cur.close()


class _MySQLCursorCtx:
    def __init__(self, conn: aiomysql.Connection, *args: Any) -> None:
        self._conn = conn
        self._args = args
        self._ctx: Any = None

    async def __aenter__(self) -> _Cursor:
        self._ctx = self._conn.cursor(*self._args)
        cur = await self._ctx.__aenter__()
        return _Cursor(cur, is_sqlite=False)

    async def __aexit__(self, *args: Any) -> None:
        if self._ctx:
            await self._ctx.__aexit__(*args)


class DbBackend:
    """Wraps either an aiomysql pool (MySQL) or a file path (SQLite)."""

    def __init__(self, inner: aiomysql.Pool | str, *, is_sqlite: bool) -> None:
        self._inner = inner
        self.is_sqlite = is_sqlite

    @classmethod
    async def from_mysql(cls, creds: "CredentialsConfig") -> "DbBackend":
        pool = await aiomysql.create_pool(
            host=creds.server,
            port=creds.port,
            user=creds.user,
            password=creds.password,
            db=creds.database,
            autocommit=True,
            minsize=2,
            maxsize=10,
            charset="utf8mb4",
            connect_timeout=10,
        )
        return cls(pool, is_sqlite=False)

    @classmethod
    def from_sqlite(cls, path: str) -> "DbBackend":
        return cls(path, is_sqlite=True)

    def close(self) -> None:
        if not self.is_sqlite:
            self._inner.close()  # type: ignore[union-attr]

    async def wait_closed(self) -> None:
        if not self.is_sqlite:
            await self._inner.wait_closed()  # type: ignore[union-attr]


@asynccontextmanager
async def get_conn(db: DbBackend) -> AsyncIterator[_Conn]:
    if db.is_sqlite:
        async with aiosqlite.connect(db._inner) as conn:  # type: ignore[arg-type]
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            yield _Conn(conn, is_sqlite=True)
    else:
        async with db._inner.acquire() as conn:  # type: ignore[union-attr]
            yield _Conn(conn, is_sqlite=False)


async def create_db_backend(
    exp_cfg: "ExperimenterConfig",
    creds: "CredentialsConfig | None",
) -> DbBackend:
    """Factory: create the correct backend from config."""
    if exp_cfg.provider == "sqlite" and exp_cfg.sqlite_path:
        return DbBackend.from_sqlite(exp_cfg.sqlite_path)
    if creds is None:
        raise ValueError("MySQL credentials required but not provided")
    return await DbBackend.from_mysql(creds)


# Backward-compat alias used in some routers
async def create_pool(creds: "CredentialsConfig") -> DbBackend:
    return await DbBackend.from_mysql(creds)
