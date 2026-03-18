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
    parser.add_argument("--config", default=None, help="Path to PyExperimenter config.yml (optional)")
    parser.add_argument("--db-config", default=None, help="Path to PyExperimenter db_config.yml (optional, not needed for SQLite)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    args = parser.parse_args()

    # Validate provided config files exist before starting uvicorn
    for label, path in [("--config", args.config), ("--db-config", args.db_config)]:
        if path is not None and not Path(path).exists():
            print(f"Error: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    # --db-config without --config is always an error
    if args.config is None and args.db_config is not None:
        print("Error: --db-config requires --config", file=sys.stderr)
        sys.exit(1)

    # If only --config is given (no --db-config), load_config will detect the provider.
    # For MySQL it will raise ValueError (db_config_path required), which we surface below.

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required. Install with: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    print(f"Starting PyExperimenter Dashboard at http://{args.host}:{args.port}")
    if args.config is None:
        print("No config files provided — starting in project-picker mode.", file=sys.stderr)

    # Store config paths in env vars so wsgi.py can read them on (re-)import
    os.environ["PY_EXP_CONFIG"] = str(Path(args.config).resolve()) if args.config else ""
    os.environ["PY_EXP_DB_CONFIG"] = str(Path(args.db_config).resolve()) if args.db_config else ""

    if args.reload:
        uvicorn.run(
            "py_experimenter_db.dashboard.wsgi:app",
            host=args.host,
            port=args.port,
            reload=True,
        )
    else:
        from py_experimenter_db.dashboard.app import create_app

        if args.config:
            from py_experimenter_db.config import load_config
            try:
                exp_cfg, creds_cfg = load_config(args.config, args.db_config)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            exp_cfg, creds_cfg = None, None

        app = create_app(exp_cfg, creds_cfg)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
