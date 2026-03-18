"""FastAPI application factory."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from py_experimenter_db.config import CredentialsConfig, ExperimenterConfig
from py_experimenter_db.dashboard.project_registry import ProjectRegistry
from py_experimenter_db.dashboard.settings import DashboardSettings, settings_from_db
from py_experimenter_db.dashboard.state import AppState
from py_experimenter_db.db.connection import create_db_backend
from py_experimenter_db.db.schema import build_schema_info
from py_experimenter_db.history.store import QueryHistoryStore

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _apply_settings_globals(templates: Jinja2Templates, settings: DashboardSettings) -> None:
    """Push mutable settings into Jinja2 globals so all templates see current values."""
    templates.env.globals["settings"] = settings


def _apply_schema_globals(templates: Jinja2Templates, state: AppState) -> None:
    """Push schema-derived globals — safe to call with schema=None (no-project mode)."""
    templates.env.globals["has_codecarbon"] = state.schema.has_codecarbon if state.schema else False
    templates.env.globals["table_name"] = state.schema.table_name if state.schema else None
    templates.env.globals["keyfields"] = state.schema.keyfields if state.schema else []
    templates.env.globals["resultfields"] = state.schema.resultfields if state.schema else []
    templates.env.globals["project_active"] = state.is_active


def _make_templates(state: AppState) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    _apply_schema_globals(templates, state)
    _apply_settings_globals(templates, state.settings)

    # Custom filter: pretty-print seconds as human-readable duration
    def fmt_duration(seconds: float | int | None) -> str:
        if seconds is None:
            return "—"
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60}s"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"

    def fmt_number(n: int | None) -> str:
        if n is None:
            return "—"
        return f"{n:,}"

    templates.env.filters["fmt_duration"] = fmt_duration
    templates.env.filters["fmt_number"] = fmt_number
    templates.env.filters["tojson"] = lambda v: json.dumps(v, default=str)

    return templates


def create_app(
    exp_cfg: ExperimenterConfig | None = None,
    creds_cfg: CredentialsConfig | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Both arguments are optional.  When omitted the dashboard starts in
    *project-picker mode*: no database connection is made and the user is
    prompted to select or upload a project from the Projects page.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        project_registry = ProjectRegistry()
        await project_registry.init()

        if exp_cfg is not None:
            db = await create_db_backend(exp_cfg, creds_cfg)
            schema = await build_schema_info(exp_cfg, db)

            history_db_path = Path.cwd() / ".py_experimenter_dashboard" / "query_history.sqlite"
            history_store = QueryHistoryStore(history_db_path)
            await history_store.init()

            raw_settings = await history_store.get_all_settings()
            dashboard_settings = settings_from_db(raw_settings)

            await project_registry.register(
                path=str(Path.cwd()),
                workspace_db=str(history_db_path),
                db_host=creds_cfg.server if creds_cfg else "",
                db_port=creds_cfg.port if creds_cfg else 0,
                db_user=creds_cfg.user if creds_cfg else "",
                db_password=creds_cfg.password if creds_cfg else "",
                db_database=creds_cfg.database if creds_cfg else (exp_cfg.sqlite_path or ""),
                db_table=exp_cfg.table.name,
                config_path=os.environ.get("PY_EXP_CONFIG", ""),
                db_config_path=os.environ.get("PY_EXP_DB_CONFIG", ""),
                config_json=json.dumps({
                    "keyfields": {k: v.type for k, v in exp_cfg.table.keyfields.items()},
                    "resultfields": dict(exp_cfg.table.resultfields),
                    "logtables": {lt: dict(cols) for lt, cols in exp_cfg.table.logtables.items()},
                    "result_timestamps": exp_cfg.table.result_timestamps,
                }),
            )

            app_state = AppState(
                db=db,
                schema=schema,
                experimenter_config=exp_cfg,
                creds=creds_cfg,
                history_store=history_store,
                history_db_path=history_db_path,
                settings=dashboard_settings,
                project_registry=project_registry,
                config_path=os.environ.get("PY_EXP_CONFIG", ""),
                db_config_path=os.environ.get("PY_EXP_DB_CONFIG", ""),
            )
        else:
            # No config supplied — project-picker mode
            app_state = AppState(project_registry=project_registry)

        app.state.dashboard = app_state
        app.state.templates = _make_templates(app_state)

        yield

        if app_state.db is not None:
            app_state.db.close()
            await app_state.db.wait_closed()

    app = FastAPI(
        title="PyExperimenter Dashboard",
        lifespan=lifespan,
    )

    _static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    # Import routers here to avoid circular imports
    from py_experimenter_db.dashboard.routers import (
        carbon,
        chat,
        config,
        experiments,
        failures,
        monitor,
        projects,
        query,
        reset,
    )

    app.include_router(monitor.router)
    app.include_router(experiments.router)
    app.include_router(failures.router)
    app.include_router(reset.router)
    app.include_router(query.router)
    app.include_router(chat.router)
    app.include_router(carbon.router)
    app.include_router(config.router)
    app.include_router(projects.router)

    return app


async def reload_settings(request: Request) -> None:
    """Persist updated settings back to the live AppState and template globals."""
    state = request.app.state.dashboard
    if state.history_store is not None:
        raw = await state.history_store.get_all_settings()
        state.settings = settings_from_db(raw)
    _apply_settings_globals(request.app.state.templates, state.settings)


def get_state(request: Request) -> AppState:
    """Helper to extract AppState from request."""
    return request.app.state.dashboard


def get_templates(request: Request) -> Jinja2Templates:
    """Helper to extract Jinja2Templates from request."""
    return request.app.state.templates


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
