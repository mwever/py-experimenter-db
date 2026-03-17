"""Async MySQL connection pool management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import aiomysql

if TYPE_CHECKING:
    from py_experimenter_db.config import CredentialsConfig


async def create_pool(creds: CredentialsConfig) -> aiomysql.Pool:
    return await aiomysql.create_pool(
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


@asynccontextmanager
async def get_conn(pool: aiomysql.Pool) -> AsyncIterator[aiomysql.Connection]:
    async with pool.acquire() as conn:
        yield conn
