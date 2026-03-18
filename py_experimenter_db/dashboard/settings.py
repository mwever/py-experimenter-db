"""Dashboard settings dataclass and serialisation helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# Environment variable names for LLM defaults
_ENV_LLM_URL   = "PY_EXP_LLM_URL"
_ENV_LLM_TOKEN = "PY_EXP_LLM_TOKEN"
_ENV_LLM_MODEL = "PY_EXP_LLM_MODEL"


@dataclass
class DashboardSettings:
    # Monitor page
    ui_refresh_interval: int = 5          # seconds between live-update polls

    # Experiments table
    default_columns: list[str] = field(
        default_factory=lambda: ["ID", "status", "machine", "creation_date", "start_date", "end_date"]
    )
    default_page_size: int = 50
    default_sort_col: str = "ID"
    default_sort_dir: str = "DESC"

    # LLM connector (chat feature)
    llm_url: str = ""          # e.g. "https://api.openai.com/v1" or "http://localhost:11434/v1"
    llm_token: str = ""        # API key / bearer token (optional for local LLMs)
    llm_model: str = "gpt-4o"  # model name passed to the API


def settings_from_db(raw: dict[str, str]) -> DashboardSettings:
    """Build a DashboardSettings from the raw key→value rows stored in SQLite."""
    s = DashboardSettings()
    if "ui_refresh_interval" in raw:
        try:
            s.ui_refresh_interval = max(1, int(raw["ui_refresh_interval"]))
        except ValueError:
            pass
    if "default_columns" in raw:
        try:
            cols = json.loads(raw["default_columns"])
            if isinstance(cols, list) and cols:
                s.default_columns = cols
        except (ValueError, TypeError):
            pass
    if "default_page_size" in raw:
        try:
            s.default_page_size = max(10, min(500, int(raw["default_page_size"])))
        except ValueError:
            pass
    if "default_sort_col" in raw:
        s.default_sort_col = raw["default_sort_col"]
    if "default_sort_dir" in raw:
        s.default_sort_dir = raw["default_sort_dir"] if raw["default_sort_dir"] in ("ASC", "DESC") else "DESC"
    # LLM fields: DB value (if non-empty) > env var > hardcoded default
    s.llm_url   = raw.get("llm_url")   or os.environ.get(_ENV_LLM_URL,   "")
    s.llm_token = raw.get("llm_token") or os.environ.get(_ENV_LLM_TOKEN, "")
    s.llm_model = raw.get("llm_model") or os.environ.get(_ENV_LLM_MODEL, "gpt-4o")
    return s


def settings_to_db(s: DashboardSettings) -> dict[str, str]:
    """Serialise a DashboardSettings to the flat key→value format for SQLite."""
    return {
        "ui_refresh_interval": str(s.ui_refresh_interval),
        "default_columns": json.dumps(s.default_columns),
        "default_page_size": str(s.default_page_size),
        "default_sort_col": s.default_sort_col,
        "default_sort_dir": s.default_sort_dir,
        "llm_url": s.llm_url,
        "llm_token": s.llm_token,
        "llm_model": s.llm_model,
    }
