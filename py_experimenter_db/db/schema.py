"""Schema introspection: merges PyExperimenter config with live DB metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import aiomysql

from py_experimenter_db.config import ExperimenterConfig
from py_experimenter_db.db.connection import DbBackend, get_conn

# Minimum columns expected on the main table (exception column is detected at runtime)
STANDARD_COLUMNS = ["ID", "status", "machine", "creation_date", "start_date", "end_date"]

# Candidate names for the exception/traceback column across PyExperimenter versions
_EXCEPTION_COLUMN_CANDIDATES = ["exception", "error", "traceback", "stderr", "error_message"]

# Allowed column name pattern (prevent injection via column names)
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def is_safe_identifier(name: str) -> bool:
    return bool(_SAFE_IDENT.match(name))


@dataclass
class SchemaInfo:
    table_name: str
    keyfields: list[str]
    resultfields: list[str]
    result_timestamps: bool
    logtable_names: list[str]           # logical names (without table prefix)
    logtable_columns: dict[str, list[str]]  # logical_name -> [col, ...]
    has_codecarbon: bool
    exception_column: str | None        # actual column name for stack traces, None if absent
    all_columns: list[str] = field(default_factory=list)  # all cols for allowlist


async def build_schema_info(cfg: ExperimenterConfig, db: DbBackend) -> SchemaInfo:
    """Introspect the live DB and combine with config to build SchemaInfo."""
    table = cfg.table.name

    # Discover which tables actually exist and the real column names on the main table
    async with get_conn(db) as conn:
        if db.is_sqlite:
            async with conn.cursor() as cur:
                await cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = {row["name"] for row in await cur.fetchall()}
                actual_columns: set[str] = set()
                if table in existing_tables:
                    await cur.execute(f"PRAGMA table_info(`{table}`)")
                    actual_columns = {row["name"] for row in await cur.fetchall()}
        else:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SHOW TABLES")
                existing_tables = {list(row.values())[0] for row in await cur.fetchall()}
                actual_columns = set()
                if table in existing_tables:
                    await cur.execute(f"SHOW COLUMNS FROM `{table}`")
                    actual_columns = {row["Field"] for row in await cur.fetchall()}

    # Detect exception column — name varies across PyExperimenter versions
    exception_column: str | None = next(
        (c for c in _EXCEPTION_COLUMN_CANDIDATES if c in actual_columns), None
    )

    # Determine which logtables exist in DB
    logtable_names: list[str] = []
    logtable_columns: dict[str, list[str]] = {}
    for lt_name, lt_fields in cfg.table.logtables.items():
        db_table_name = f"{table}__{lt_name}"
        if db_table_name in existing_tables:
            logtable_names.append(lt_name)
            logtable_columns[lt_name] = list(lt_fields.keys())

    has_codecarbon = f"{table}_codecarbon" in existing_tables

    keyfields = list(cfg.table.keyfields.keys())
    resultfields = list(cfg.table.resultfields.keys())

    # Build full column allowlist
    all_cols = list(STANDARD_COLUMNS)
    if exception_column:
        all_cols.append(exception_column)
    all_cols.extend(keyfields)
    all_cols.extend(resultfields)
    if cfg.table.result_timestamps:
        all_cols.extend(f"{rf}_timestamp" for rf in resultfields)

    return SchemaInfo(
        table_name=table,
        keyfields=keyfields,
        resultfields=resultfields,
        result_timestamps=cfg.table.result_timestamps,
        logtable_names=logtable_names,
        logtable_columns=logtable_columns,
        has_codecarbon=has_codecarbon,
        exception_column=exception_column,
        all_columns=all_cols,
    )
