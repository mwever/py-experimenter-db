"""Execute LLM-generated Python code in a subprocess with DB context injected."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from py_experimenter_db.config import CredentialsConfig
from py_experimenter_db.db.schema import SchemaInfo


@dataclass
class RunResult:
    stdout: str
    stderr: str
    plots: list[str] = field(default_factory=list)   # relative filenames inside output_dir
    error: str | None = None


def _build_preamble(
    creds: CredentialsConfig | None,
    schema: SchemaInfo,
    output_dir: str,
    sqlite_path: str | None = None,
) -> str:
    """Return Python source injected before the user code."""
    logtable_info = {
        f"{schema.table_name}__{lt}": list(schema.logtable_columns.get(lt, []))
        for lt in schema.logtable_names
    }

    if sqlite_path:
        db_block = textwrap.dedent(f"""\
            import sqlite3 as _sqlite3
            _DB_PATH = {sqlite_path!r}

            def query(sql, **kw):
                \"\"\"Execute SQL and return a pandas DataFrame.\"\"\"
                conn = _sqlite3.connect(_DB_PATH)
                try:
                    return pd.read_sql_query(sql, conn, **kw)
                finally:
                    conn.close()
        """)
    else:
        db_block = textwrap.dedent(f"""\
            import pymysql
            _DB = dict(
                host={creds.server!r},
                port={creds.port!r},
                user={creds.user!r},
                password={creds.password!r},
                database={creds.database!r},
            )

            def query(sql, **kw):
                \"\"\"Execute SQL and return a pandas DataFrame.\"\"\"
                conn = pymysql.connect(**_DB)
                try:
                    return pd.read_sql(sql, conn, **kw)
                finally:
                    conn.close()
        """)

    return textwrap.dedent(f"""\
        import os, sys, re, json
        import pandas as pd
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        # ── DB connection helpers ───────────────────────────────────────
        {db_block}
        # ── Schema constants ───────────────────────────────────────────
        TABLE        = {schema.table_name!r}
        KEYFIELDS    = {schema.keyfields!r}
        RESULTFIELDS = {schema.resultfields!r}
        LOGTABLES    = {logtable_info!r}

        # ── Auto-save plots ─────────────────────────────────────────────
        _OUT = {output_dir!r}
        os.makedirs(_OUT, exist_ok=True)
        _plot_n = [0]

        def _save_show():
            _plot_n[0] += 1
            path = os.path.join(_OUT, f'plot_{{_plot_n[0]}}.png')
            plt.savefig(path, dpi=150, bbox_inches='tight')
            plt.close()
            print(f'[PLOT]{{path}}', flush=True)

        plt.show = _save_show

        # ── User code ───────────────────────────────────────────────────
    """)


async def run_code(
    code: str,
    creds: CredentialsConfig | None,
    schema: SchemaInfo,
    output_dir: Path,
    sqlite_path: str | None = None,
) -> RunResult:
    preamble = _build_preamble(creds, schema, str(output_dir), sqlite_path=sqlite_path)
    full_code = preamble + code

    fd, tmpfile = tempfile.mkstemp(suffix=".py", prefix="pyexp_chat_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(full_code)

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            tmpfile,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return RunResult(stdout="", stderr="", error="Execution timed out (60 s).")

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        plot_paths = re.findall(r"\[PLOT\](.+)", stdout)
        stdout_clean = re.sub(r"\[PLOT\].+\n?", "", stdout).strip()

        # Return only filenames (relative), not full paths
        plots = [
            os.path.basename(p.strip())
            for p in plot_paths
            if os.path.exists(p.strip())
        ]

        return RunResult(stdout=stdout_clean, stderr=stderr.strip(), plots=plots)

    except Exception as exc:
        return RunResult(stdout="", stderr="", error=str(exc))
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass
