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

if _config_path:
    exp_cfg, creds_cfg = load_config(_config_path, _db_config_path or None)
else:
    exp_cfg, creds_cfg = None, None

app = create_app(exp_cfg, creds_cfg)
