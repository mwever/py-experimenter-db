"""All async SQL query functions for the dashboard."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import aiomysql

from py_experimenter_db.db.connection import get_conn
from py_experimenter_db.db.schema import SchemaInfo, is_safe_identifier


# ---------------------------------------------------------------------------
# Monitor / Stats
# ---------------------------------------------------------------------------

@dataclass
class MonitorStats:
    total: int
    done: int
    running: int
    error: int
    pending: int
    avg_runtime_seconds: float | None
    eta_seconds: int | None
    active_worker_count: int


async def get_monitor_stats(pool: aiomysql.Pool, schema: SchemaInfo) -> MonitorStats:
    t = schema.table_name
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(status = 'done') AS done,
                    SUM(status = 'running') AS running,
                    SUM(status = 'error') AS error,
                    SUM(status = 'created') AS pending,
                    AVG(CASE WHEN status = 'done' AND start_date IS NOT NULL AND end_date IS NOT NULL
                             THEN TIMESTAMPDIFF(SECOND, start_date, end_date) END) AS avg_runtime_seconds
                FROM `{t}`
            """)
            row = await cur.fetchone()

            await cur.execute(f"SELECT COUNT(DISTINCT machine) AS wc FROM `{t}` WHERE status = 'running'")
            worker_row = await cur.fetchone()

    total = int(row["total"] or 0)
    done = int(row["done"] or 0)
    running = int(row["running"] or 0)
    error = int(row["error"] or 0)
    pending = int(row["pending"] or 0)
    avg_rt = float(row["avg_runtime_seconds"]) if row["avg_runtime_seconds"] is not None else None
    active_workers = int(worker_row["wc"] or 0)

    eta: int | None = None
    if avg_rt and active_workers and pending:
        eta = int((pending / active_workers) * avg_rt)

    return MonitorStats(
        total=total,
        done=done,
        running=running,
        error=error,
        pending=pending,
        avg_runtime_seconds=avg_rt,
        eta_seconds=eta,
        active_worker_count=active_workers,
    )


async def get_workers(pool: aiomysql.Pool, schema: SchemaInfo) -> list[dict[str, Any]]:
    t = schema.table_name
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"""
                SELECT machine, COUNT(*) AS job_count, MIN(start_date) AS oldest_start
                FROM `{t}`
                WHERE status = 'running'
                GROUP BY machine
                ORDER BY job_count DESC
            """)
            return list(await cur.fetchall())


# ---------------------------------------------------------------------------
# Experiment Table
# ---------------------------------------------------------------------------

@dataclass
class ExperimentPage:
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int


def _build_where(
    search: str | None,
    status_filter: list[str] | None,
    keyfield_filters: dict[str, str],
    schema: SchemaInfo,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if status_filter:
        placeholders = ", ".join(["%s"] * len(status_filter))
        clauses.append(f"status IN ({placeholders})")
        params.extend(status_filter)

    for kf, val in keyfield_filters.items():
        if val and is_safe_identifier(kf) and kf in schema.keyfields:
            clauses.append(f"`{kf}` = %s")
            params.append(val)

    if search:
        like_cols = ["ID", "machine"] + schema.keyfields
        like_clauses = [f"CAST(`{c}` AS CHAR) LIKE %s" for c in like_cols]
        clauses.append(f"({' OR '.join(like_clauses)})")
        params.extend([f"%{search}%"] * len(like_cols))

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


async def get_experiments_page(
    pool: aiomysql.Pool,
    schema: SchemaInfo,
    columns: list[str],
    page: int = 1,
    page_size: int = 50,
    sort_col: str = "ID",
    sort_dir: str = "DESC",
    search: str | None = None,
    status_filter: list[str] | None = None,
    keyfield_filters: dict[str, str] | None = None,
) -> ExperimentPage:
    t = schema.table_name

    # Validate columns against allowlist
    safe_cols = [c for c in columns if is_safe_identifier(c) and c in schema.all_columns]
    if not safe_cols:
        safe_cols = ["ID", "status", "machine"] + schema.keyfields[:5]
    col_list = ", ".join(f"`{c}`" for c in safe_cols)

    if not is_safe_identifier(sort_col) or sort_col not in schema.all_columns:
        sort_col = "ID"
    sort_dir = "ASC" if sort_dir.upper() == "ASC" else "DESC"

    where, params = _build_where(search, status_filter, keyfield_filters or {}, schema)
    offset = (page - 1) * page_size

    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT COUNT(*) AS cnt FROM `{t}` {where}", params)
            total = int((await cur.fetchone())["cnt"])

            await cur.execute(
                f"SELECT {col_list} FROM `{t}` {where} ORDER BY `{sort_col}` {sort_dir} LIMIT %s OFFSET %s",
                params + [page_size, offset],
            )
            rows = list(await cur.fetchall())

    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)

    return ExperimentPage(rows=rows, total=total, page=page, page_size=page_size, total_pages=total_pages)


async def get_experiment_detail(
    pool: aiomysql.Pool, schema: SchemaInfo, experiment_id: int
) -> dict[str, Any] | None:
    t = schema.table_name
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT * FROM `{t}` WHERE ID = %s", (experiment_id,))
            return await cur.fetchone()


async def get_logtable_rows(
    pool: aiomysql.Pool, schema: SchemaInfo, experiment_id: int, logtable_name: str
) -> list[dict[str, Any]]:
    db_name = f"{schema.table_name}__{logtable_name}"
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                f"SELECT * FROM `{db_name}` WHERE experiment_id = %s ORDER BY ID ASC",
                (experiment_id,),
            )
            return list(await cur.fetchall())


async def get_keyfield_distinct_values(
    pool: aiomysql.Pool, schema: SchemaInfo
) -> dict[str, list[Any]]:
    """Get distinct values for each keyfield for filter dropdowns."""
    t = schema.table_name
    result: dict[str, list[Any]] = {}
    async with get_conn(pool) as conn:
        async with conn.cursor() as cur:
            for kf in schema.keyfields:
                await cur.execute(f"SELECT DISTINCT `{kf}` FROM `{t}` ORDER BY `{kf}`")
                rows = await cur.fetchall()
                result[kf] = [r[0] for r in rows]
    return result


# ---------------------------------------------------------------------------
# Failure Analysis
# ---------------------------------------------------------------------------

@dataclass
class FailureGroup:
    error_type: str
    count: int
    experiment_ids: list[int]
    sample_exception: str


async def get_failure_groups(pool: aiomysql.Pool, schema: SchemaInfo) -> list[FailureGroup]:
    t = schema.table_name
    exc = schema.exception_column
    if not exc:
        return []
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"""
                SELECT
                    TRIM(SUBSTRING_INDEX(
                        TRIM(TRAILING '\\n' FROM TRIM(TRAILING '\\r' FROM `{exc}`)),
                        '\\n', -1
                    )) AS error_type,
                    COUNT(*) AS cnt,
                    GROUP_CONCAT(ID ORDER BY ID SEPARATOR ',') AS ids,
                    MIN(`{exc}`) AS sample_exception
                FROM `{t}`
                WHERE status = 'error' AND `{exc}` IS NOT NULL AND `{exc}` != ''
                GROUP BY error_type
                ORDER BY cnt DESC
            """)
            rows = await cur.fetchall()

    groups: list[FailureGroup] = []
    for row in rows:
        ids = [int(i) for i in str(row["ids"]).split(",") if i]
        groups.append(FailureGroup(
            error_type=row["error_type"] or "(no message)",
            count=int(row["cnt"]),
            experiment_ids=ids,
            sample_exception=row["sample_exception"] or "",
        ))
    return groups


async def get_experiment_exception(
    pool: aiomysql.Pool, schema: SchemaInfo, experiment_id: int
) -> str | None:
    t = schema.table_name
    exc = schema.exception_column
    if not exc:
        return None
    async with get_conn(pool) as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT `{exc}` FROM `{t}` WHERE ID = %s", (experiment_id,))
            row = await cur.fetchone()
            return row[0] if row else None


async def rerun_experiments(
    pool: aiomysql.Pool,
    schema: SchemaInfo,
    experiment_ids: list[int],
    delete_logtable_data: bool = False,
    delete_codecarbon: bool = False,
) -> int:
    """Reset experiments to 'created' state. Returns number of rows updated."""
    if not experiment_ids:
        return 0
    t = schema.table_name
    placeholders = ", ".join(["%s"] * len(experiment_ids))

    # Build SET clause to clear all result fields too
    result_clears = ", ".join(f"`{rf}` = NULL" for rf in schema.resultfields)
    exc_clear = f", `{schema.exception_column}` = NULL" if schema.exception_column else ""
    set_clause = f"status = 'created', machine = NULL, start_date = NULL, end_date = NULL{exc_clear}"
    if result_clears:
        set_clause = f"{set_clause}, {result_clears}"

    async with get_conn(pool) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE `{t}` SET {set_clause} WHERE ID IN ({placeholders})",
                experiment_ids,
            )
            updated = cur.rowcount

            if delete_logtable_data:
                for lt_name in schema.logtable_names:
                    db_lt = f"{t}__{lt_name}"
                    await cur.execute(
                        f"DELETE FROM `{db_lt}` WHERE experiment_id IN ({placeholders})",
                        experiment_ids,
                    )

            if delete_codecarbon and schema.has_codecarbon:
                cc_table = f"{t}_codecarbon"
                await cur.execute(
                    f"DELETE FROM `{cc_table}` WHERE experiment_id IN ({placeholders})",
                    experiment_ids,
                )

    return updated


@dataclass
class ResetCandidate:
    id: int
    status: str
    creation_date: str | None
    keyfield_values: dict[str, str]   # keyfield_name -> value


def _parse_keyfield_filter(col: str, raw: str) -> tuple[str, list[Any]] | None:
    """Parse a keyfield filter expression into (sql_fragment, params) or None.

    Supported syntax (examples):
      foo           → exact match:   `col` = 'foo'
      foo, bar      → IN list:       `col` IN ('foo', 'bar')
      >=3           → comparison:    `col` >= 3
      <=10          → comparison:    `col` <= 10
      >3            → comparison:    `col` > 3
      <10           → comparison:    `col` < 10
      !=foo         → not equal:     `col` != 'foo'
      1-10          → numeric range: `col` BETWEEN 1 AND 10
      *foo*         → wildcard LIKE: `col` LIKE '%foo%'
    """
    val = raw.strip()
    if not val:
        return None

    # Numeric range: 1-10 or 1..10 (must not look like a negative number)
    range_m = re.match(r'^(-?\d+(?:\.\d+)?)\s*(?:\.\.|-(?=\d))\s*(-?\d+(?:\.\d+)?)$', val)
    if range_m:
        return f"`{col}` BETWEEN %s AND %s", [range_m.group(1), range_m.group(2)]

    # Comparison operators: >=, <=, !=, >, <
    cmp_m = re.match(r'^(>=|<=|!=|>|<)\s*(.+)$', val)
    if cmp_m:
        op, operand = cmp_m.group(1), cmp_m.group(2).strip()
        return f"`{col}` {op} %s", [operand]

    # Multiple comma-separated values → IN (...)
    if ',' in val:
        parts = [p.strip() for p in val.split(',') if p.strip()]
        phs = ', '.join(['%s'] * len(parts))
        return f"`{col}` IN ({phs})", parts

    # Wildcard: user-supplied * becomes SQL %
    if '*' in val:
        return f"`{col}` LIKE %s", [val.replace('*', '%')]

    # Default: exact match
    return f"`{col}` = %s", [val]


async def search_experiments_for_reset(
    pool: aiomysql.Pool,
    schema: SchemaInfo,
    statuses: list[str],
    keyfield_filters: dict[str, str],   # name -> expression (empty = no filter)
    limit: int = 1000,
) -> list[ResetCandidate]:
    """Return experiments matching the given status + keyfield filters."""
    t = schema.table_name
    kf_cols = [kf for kf in schema.keyfields if is_safe_identifier(kf)]

    # Build WHERE clause
    where_parts = []
    params: list[Any] = []

    if statuses:
        placeholders = ", ".join(["%s"] * len(statuses))
        where_parts.append(f"status IN ({placeholders})")
        params.extend(statuses)

    for kf in kf_cols:
        parsed = _parse_keyfield_filter(kf, keyfield_filters.get(kf, ""))
        if parsed:
            frag, frag_params = parsed
            where_parts.append(frag)
            params.extend(frag_params)

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    kf_select = ", ".join(f"`{kf}`" for kf in kf_cols)
    if kf_select:
        kf_select = ", " + kf_select

    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                f"SELECT ID, status, creation_date{kf_select} FROM `{t}` {where} ORDER BY ID LIMIT %s",
                params + [limit],
            )
            rows = await cur.fetchall()

    result = []
    for row in rows:
        kv = {kf: "" if row.get(kf) is None else str(row[kf]) for kf in kf_cols}
        result.append(ResetCandidate(
            id=int(row["ID"]),
            status=row["status"] or "",
            creation_date=str(row["creation_date"]) if row.get("creation_date") else None,
            keyfield_values=kv,
        ))
    return result


# ---------------------------------------------------------------------------
# Schema introspection for Query Tool
# ---------------------------------------------------------------------------

@dataclass
class ColumnInfo:
    name: str
    col_type: str
    nullable: bool
    key: str        # PRI / MUL / UNI / ""
    default: str | None


@dataclass
class TableSchema:
    table_name: str
    label: str      # human-readable label shown in UI
    columns: list[ColumnInfo]


async def get_db_schema(pool: aiomysql.Pool, schema: SchemaInfo) -> list[TableSchema]:
    """Return column-level schema for all dashboard-relevant tables.

    Discovers logtables directly from the DB (tables whose name starts with
    ``{main_table}__``) so the result is independent of the cached schema.
    """
    t = schema.table_name
    lt_prefix = f"{t}__"
    cc_table = f"{t}_codecarbon"

    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Discover all existing tables in the DB
            await cur.execute("SHOW TABLES")
            existing: set[str] = {list(row.values())[0] for row in await cur.fetchall()}

            # Build ordered list: main → logtables (sorted) → codecarbon
            tables_to_fetch: list[tuple[str, str]] = [(t, "Main table")]
            for db_table in sorted(existing):
                if db_table.startswith(lt_prefix):
                    lt_name = db_table[len(lt_prefix):]
                    tables_to_fetch.append((db_table, f"Logtable: {lt_name}"))
            if cc_table in existing:
                tables_to_fetch.append((cc_table, "CodeCarbon"))

            result: list[TableSchema] = []
            for db_table, label in tables_to_fetch:
                if db_table not in existing:
                    continue
                await cur.execute(f"SHOW COLUMNS FROM `{db_table}`")
                rows = await cur.fetchall()
                columns = [
                    ColumnInfo(
                        name=row["Field"],
                        col_type=row["Type"],
                        nullable=row["Null"] == "YES",
                        key=row["Key"] or "",
                        default=row["Default"],
                    )
                    for row in rows
                ]
                result.append(TableSchema(table_name=db_table, label=label, columns=columns))

    return result


# ---------------------------------------------------------------------------
# SQL Query Tool
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    truncated: bool
    error: str | None = None


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--.*$", re.MULTILINE)
_MAX_ROWS = 2000


def validate_select_query(sql: str) -> str | None:
    """Returns an error string if the query is not a safe SELECT, else None."""
    cleaned = _BLOCK_COMMENT.sub("", sql)
    cleaned = _LINE_COMMENT.sub("", cleaned)
    tokens = cleaned.strip().split()
    if not tokens:
        return "Empty query"
    if tokens[0].upper() != "SELECT":
        return "Only SELECT queries are allowed"
    upper = cleaned.upper()
    if re.search(r"\bINTO\s+(OUTFILE|DUMPFILE|@)", upper):
        return "SELECT INTO is not allowed"
    return None


async def execute_query(pool: aiomysql.Pool, sql: str) -> QueryResult:
    err = validate_select_query(sql)
    if err:
        return QueryResult(columns=[], rows=[], row_count=0, truncated=False, error=err)

    try:
        async with get_conn(pool) as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                rows = await cur.fetchmany(_MAX_ROWS + 1)
                columns = [d[0] for d in cur.description] if cur.description else []

        truncated = len(rows) > _MAX_ROWS
        return QueryResult(
            columns=columns,
            rows=list(rows[:_MAX_ROWS]),
            row_count=len(rows[:_MAX_ROWS]),
            truncated=truncated,
        )
    except Exception as e:
        return QueryResult(columns=[], rows=[], row_count=0, truncated=False, error=str(e))


# ---------------------------------------------------------------------------
# Carbon Footprint
# ---------------------------------------------------------------------------

@dataclass
class CarbonSummary:
    total_kwh: float
    total_kg_co2: float
    avg_rate_kg_sec: float
    n_runs: int
    n_experiments: int


async def get_carbon_summary(pool: aiomysql.Pool, schema: SchemaInfo) -> CarbonSummary | None:
    if not schema.has_codecarbon:
        return None
    t = f"{schema.table_name}_codecarbon"
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"""
                SELECT
                    COALESCE(SUM(energy_consumed_kw), 0) AS total_kwh,
                    COALESCE(SUM(emissions_kg), 0) AS total_kg_co2,
                    COALESCE(AVG(emissions_rate_kg_sec), 0) AS avg_rate,
                    COUNT(*) AS n_runs,
                    COUNT(DISTINCT experiment_id) AS n_experiments
                FROM `{t}`
            """)
            row = await cur.fetchone()
    if row is None:
        return None
    return CarbonSummary(
        total_kwh=float(row["total_kwh"] or 0),
        total_kg_co2=float(row["total_kg_co2"] or 0),
        avg_rate_kg_sec=float(row["avg_rate"] or 0),
        n_runs=int(row["n_runs"] or 0),
        n_experiments=int(row["n_experiments"] or 0),
    )


async def get_carbon_timeseries(pool: aiomysql.Pool, schema: SchemaInfo) -> list[dict[str, Any]]:
    if not schema.has_codecarbon:
        return []
    t = f"{schema.table_name}_codecarbon"
    async with get_conn(pool) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"""
                SELECT experiment_id, codecarbon_timestamp, emissions_kg,
                       energy_consumed_kw, duration_seconds,
                       cpu_power_watt, gpu_power_watt, ram_power_watt
                FROM `{t}`
                ORDER BY codecarbon_timestamp ASC
            """)
            rows = await cur.fetchall()
    # Convert datetime objects to strings for JSON serialization
    result = []
    for row in rows:
        d = dict(row)
        if d.get("codecarbon_timestamp") is not None:
            d["codecarbon_timestamp"] = d["codecarbon_timestamp"].isoformat()
        result.append(d)
    return result
