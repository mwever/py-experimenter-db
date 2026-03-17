"""CLI entry point for py-experimenter-dashboard."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="py-experimenter-dashboard",
        description="Web dashboard for PyExperimenter experiments",
    )
    parser.add_argument("--config", required=True, help="Path to PyExperimenter config.yml")
    parser.add_argument("--db-config", required=True, help="Path to PyExperimenter db_config.yml")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    args = parser.parse_args()

    # Validate config files exist before starting uvicorn
    for label, path in [("--config", args.config), ("--db-config", args.db_config)]:
        if not Path(path).exists():
            print(f"Error: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required. Install with: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    print(f"Starting PyExperimenter Dashboard at http://{args.host}:{args.port}")

    # Store config paths in env vars so wsgi.py can read them on (re-)import
    os.environ["PY_EXP_CONFIG"] = str(Path(args.config).resolve())
    os.environ["PY_EXP_DB_CONFIG"] = str(Path(args.db_config).resolve())

    if args.reload:
        # --reload requires an import string, not an app object
        uvicorn.run(
            "py_experimenter_db.dashboard.wsgi:app",
            host=args.host,
            port=args.port,
            reload=True,
        )
    else:
        from py_experimenter_db.config import load_config
        from py_experimenter_db.dashboard.app import create_app

        exp_cfg, creds_cfg = load_config(args.config, args.db_config)
        app = create_app(exp_cfg, creds_cfg)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
