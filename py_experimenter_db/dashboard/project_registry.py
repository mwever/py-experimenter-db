"""Global project registry: tracks all past dashboard runs across the system."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

GLOBAL_DB_PATH = Path.home() / ".py_experimenter_dashboard" / "projects.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    path        TEXT    NOT NULL UNIQUE,
    workspace_db TEXT   NOT NULL,
    db_host     TEXT    NOT NULL,
    db_port     INTEGER NOT NULL,
    db_user     TEXT    NOT NULL,
    db_password TEXT    NOT NULL,
    db_database TEXT    NOT NULL,
    db_table    TEXT    NOT NULL,
    config_path    TEXT NOT NULL DEFAULT '',
    db_config_path TEXT NOT NULL DEFAULT '',
    config_json TEXT    NOT NULL DEFAULT '{}',
    last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS global_memory (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    content     TEXT    NOT NULL DEFAULT '',
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class ProjectEntry:
    id: int
    name: str
    path: str
    workspace_db: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_database: str
    db_table: str
    config_path: str
    db_config_path: str
    config_json: str   # serialised ExperimenterConfig table section (snapshot)
    last_seen: str
    created_at: str

    def config_data(self) -> dict:
        try:
            return json.loads(self.config_json)
        except Exception:
            return {}


class ProjectRegistry:
    def __init__(self, db_path: Path = GLOBAL_DB_PATH) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        stmts = [s.strip() for s in _SCHEMA.split(";") if s.strip()]
        async with aiosqlite.connect(self.db_path) as db:
            for stmt in stmts:
                await db.execute(stmt)
            # Migrate existing DBs that pre-date these columns
            for col, default in (("config_path", "''"), ("db_config_path", "''")):
                try:
                    await db.execute(
                        f"ALTER TABLE projects ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                    )
                except Exception:
                    pass  # column already exists
            await db.commit()

    async def register(
        self,
        path: str,
        workspace_db: str,
        db_host: str,
        db_port: int,
        db_user: str,
        db_password: str,
        db_database: str,
        db_table: str,
        config_path: str = "",
        db_config_path: str = "",
        config_json: str = "{}",
    ) -> ProjectEntry:
        name = Path(path).name or path
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO projects
                    (name, path, workspace_db, db_host, db_port, db_user,
                     db_password, db_database, db_table,
                     config_path, db_config_path, config_json,
                     last_seen, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    workspace_db   = excluded.workspace_db,
                    db_host        = excluded.db_host,
                    db_port        = excluded.db_port,
                    db_user        = excluded.db_user,
                    db_password    = excluded.db_password,
                    db_database    = excluded.db_database,
                    db_table       = excluded.db_table,
                    config_path    = excluded.config_path,
                    db_config_path = excluded.db_config_path,
                    config_json    = excluded.config_json,
                    last_seen      = excluded.last_seen
                """,
                (name, path, workspace_db, db_host, db_port, db_user,
                 db_password, db_database, db_table,
                 config_path, db_config_path, config_json, now, now),
            )
            await db.commit()
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects WHERE path = ?", (path,)
            ) as cur:
                row = await cur.fetchone()
        return _to_entry(row)

    async def get_all(self) -> list[ProjectEntry]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects ORDER BY last_seen DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [_to_entry(r) for r in rows]

    async def get_by_id(self, project_id: int) -> ProjectEntry | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ) as cur:
                row = await cur.fetchone()
        return _to_entry(row) if row else None

    async def get_global_memory(self) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT content FROM global_memory WHERE id = 1"
            ) as cur:
                row = await cur.fetchone()
        return row["content"] if row else ""

    async def set_global_memory(self, content: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO global_memory (id, content, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    content    = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (content, now),
            )
            await db.commit()


def _to_entry(row) -> ProjectEntry:
    return ProjectEntry(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        workspace_db=row["workspace_db"],
        db_host=row["db_host"],
        db_port=row["db_port"],
        db_user=row["db_user"],
        db_password=row["db_password"],
        db_database=row["db_database"],
        db_table=row["db_table"],
        config_path=row["config_path"] or "",
        db_config_path=row["db_config_path"] or "",
        config_json=row["config_json"],
        last_seen=row["last_seen"],
        created_at=row["created_at"],
    )
