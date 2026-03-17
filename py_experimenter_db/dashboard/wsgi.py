"""WSGI/ASGI entry point for uvicorn --reload.

Reads config paths from environment variables set by the CLI.
Import string: py_experimenter_db.dashboard.wsgi:app
"""

from __future__ import annotations

import os

from py_experimenter_db.config import load_config
from py_experimenter_db.dashboard.app import create_app

_config_path = os.environ.get("PY_EXP_CONFIG", "")
_db_config_path = os.environ.get("PY_EXP_DB_CONFIG", "")

if not _config_path or not _db_config_path:
    raise RuntimeError(
        "PY_EXP_CONFIG and PY_EXP_DB_CONFIG environment variables must be set "
        "before importing py_experimenter_db.dashboard.wsgi"
    )

exp_cfg, creds_cfg = load_config(_config_path, _db_config_path)
app = create_app(exp_cfg, creds_cfg)
