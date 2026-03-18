"""Projects router: multi-project management and workspace switching."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)

import yaml
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from py_experimenter_db.config import (
    CredentialsConfig,
    ExperimenterConfig,
    KeyfieldConfig,
    TableConfig,
    load_config,
)
from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.dashboard.project_registry import ProjectEntry
from py_experimenter_db.dashboard.settings import settings_from_db
from py_experimenter_db.db.connection import create_db_backend
from py_experimenter_db.db.schema import build_schema_info
from py_experimenter_db.history.store import QueryHistoryStore

router = APIRouter(prefix="/projects")

_WORKSPACES_DIR = Path.home() / ".py_experimenter_dashboard" / "workspaces"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _activate_state(
    request: Request,
    new_exp_cfg: ExperimenterConfig,
    new_creds: CredentialsConfig | None,
    workspace_db: Path,
    config_path: str,
    db_config_path: str,
) -> None:
    """Connect to new DB and atomically swap app state. Closes old connection."""
    from py_experimenter_db.dashboard.app import _apply_schema_globals

    new_db = await create_db_backend(new_exp_cfg, new_creds)
    new_schema = await build_schema_info(new_exp_cfg, new_db)

    new_store = QueryHistoryStore(workspace_db)
    await new_store.init()
    raw_settings = await new_store.get_all_settings()
    new_settings = settings_from_db(raw_settings)

    state = get_state(request)
    old_db = state.db
    state.db = new_db
    state.schema = new_schema
    state.creds = new_creds if new_exp_cfg.provider != "sqlite" else None
    state.experimenter_config = new_exp_cfg
    state.history_store = new_store
    state.history_db_path = workspace_db
    state.settings = new_settings
    state.config_path = config_path
    state.db_config_path = db_config_path
    _apply_schema_globals(request.app.state.templates, state)

    if old_db is not None:
        old_db.close()
        await old_db.wait_closed()


def _build_yaml_content(body: dict[str, Any]) -> tuple[str, str | None]:
    """Generate config.yml content (and db_config.yml for MySQL) from wizard form body.

    Returns (config_yaml, db_config_yaml_or_None).
    """
    provider = body.get("provider", "sqlite")
    table_name = (body.get("table_name") or "").strip()
    if not table_name:
        raise ValueError("Table name is required")

    kf_data: dict[str, Any] = {}
    for kf in body.get("keyfields", []):
        name = (kf.get("name") or "").strip()
        if not name:
            continue
        typ = (kf.get("type") or "VARCHAR(255)").strip()
        values_raw = (kf.get("values") or "").strip()
        if values_raw:
            kf_data[name] = {"type": typ, "values": [v.strip() for v in values_raw.split(",") if v.strip()]}
        else:
            kf_data[name] = {"type": typ}

    rf_data: dict[str, str] = {}
    for rf in body.get("resultfields", []):
        name = (rf.get("name") or "").strip()
        if name:
            rf_data[name] = (rf.get("type") or "TEXT").strip()

    lt_data: dict[str, dict[str, str]] = {}
    for lt in body.get("logtables", []):
        lt_name = (lt.get("name") or "").strip()
        if not lt_name:
            continue
        cols: dict[str, str] = {}
        for col in lt.get("columns", []):
            col_name = (col.get("name") or "").strip()
            if col_name:
                cols[col_name] = (col.get("type") or "TEXT").strip()
        lt_data[lt_name] = cols

    table_section: dict[str, Any] = {"name": table_name}
    if kf_data:
        table_section["keyfields"] = kf_data
    if rf_data:
        table_section["resultfields"] = rf_data
    if lt_data:
        table_section["logtables"] = lt_data

    if provider == "sqlite":
        sqlite_path = (body.get("sqlite_path") or "experiments.db").strip()
        db_section: dict[str, Any] = {"provider": "sqlite", "database": sqlite_path, "table": table_section}
    else:
        db_section = {
            "provider": "mysql",
            "database": (body.get("db_database") or "").strip(),
            "table": table_section,
        }

    config_yaml = yaml.dump(
        {"PY_EXPERIMENTER": {"Database": db_section}},
        default_flow_style=False, sort_keys=False, allow_unicode=True,
    )

    db_config_yaml: str | None = None
    if provider == "mysql":
        db_config_yaml = yaml.dump(
            {
                "CREDENTIALS": {
                    "Database": {
                        "user": (body.get("db_user") or "").strip(),
                        "password": body.get("db_password") or "",
                    },
                    "Connection": {
                        "Standard": {
                            "server": (body.get("db_host") or "localhost").strip(),
                            "port": int(body.get("db_port") or 3306),
                        }
                    },
                }
            },
            default_flow_style=False, sort_keys=False, allow_unicode=True,
        )

    return config_yaml, db_config_yaml


def _build_edit_data(project: ProjectEntry) -> dict[str, Any]:
    """Reconstruct wizard form state from a ProjectEntry.

    Prefers reading from YAML files (preserves keyfield values);
    falls back to config_json snapshot.
    """
    # --- preferred path: parse YAML files ---
    if project.config_path and Path(project.config_path).exists():
        try:
            db_arg = (
                project.db_config_path
                if project.db_config_path and Path(project.db_config_path).exists()
                else None
            )
            exp_cfg, creds = load_config(project.config_path, db_arg)
            provider = exp_cfg.provider
            kf_list = [
                {
                    "id": i,
                    "name": k,
                    "type": v.type,
                    "values": ", ".join(str(x) for x in v.values) if v.values else "",
                }
                for i, (k, v) in enumerate(exp_cfg.table.keyfields.items())
            ]
            rf_list = [
                {"id": len(kf_list) + i, "name": k, "type": v}
                for i, (k, v) in enumerate(exp_cfg.table.resultfields.items())
            ]
            lt_list: list[dict[str, Any]] = []
            lt_base = len(kf_list) + len(rf_list)
            for li, (lt_name, cols) in enumerate(exp_cfg.table.logtables.items()):
                lt_list.append({
                    "id": lt_base + li,
                    "name": lt_name,
                    "columns": [
                        {"id": (lt_base + li) * 100 + j, "name": c, "type": t}
                        for j, (c, t) in enumerate(cols.items())
                    ],
                })
            nid = lt_base + len(lt_list) + 1
            return {
                "project_id": project.id,
                "step": 3,
                "provider": provider,
                "sqlite_path": exp_cfg.sqlite_path or project.db_database or "experiments.db",
                "db_host": creds.server if creds else project.db_host,
                "db_port": creds.port if creds else project.db_port,
                "db_user": creds.user if creds else project.db_user,
                "db_password": creds.password if creds else project.db_password,
                "db_database": exp_cfg.database if provider == "mysql" else "",
                "table_name": exp_cfg.table.name,
                "keyfields": kf_list or [{"id": 0, "name": "", "type": "VARCHAR(255)", "values": ""}],
                "resultfields": rf_list,
                "logtables": lt_list,
                "_nid": nid,
            }
        except Exception as exc:
            _log.warning("_build_edit_data YAML path failed for project %s: %s", project.id, exc)

    # --- fallback: registry snapshot ---
    cfg_data = project.config_data()
    provider = "sqlite" if not project.db_host else "mysql"
    kf_list = [
        {"id": i, "name": k, "type": v, "values": ""}
        for i, (k, v) in enumerate(cfg_data.get("keyfields", {}).items())
    ]
    rf_list = [
        {"id": len(kf_list) + i, "name": k, "type": v}
        for i, (k, v) in enumerate(cfg_data.get("resultfields", {}).items())
    ]
    lt_list = []
    lt_base = len(kf_list) + len(rf_list)
    for li, (lt_name, cols) in enumerate(cfg_data.get("logtables", {}).items()):
        lt_list.append({
            "id": lt_base + li,
            "name": lt_name,
            "columns": [
                {"id": (lt_base + li) * 100 + j, "name": c, "type": t}
                for j, (c, t) in enumerate(cols.items())
            ],
        })
    nid = lt_base + len(lt_list) + 1
    return {
        "project_id": project.id,
        "step": 3,
        "provider": provider,
        "sqlite_path": project.db_database if provider == "sqlite" else "experiments.db",
        "db_host": project.db_host,
        "db_port": project.db_port,
        "db_user": project.db_user,
        "db_password": project.db_password,
        "db_database": project.db_database if provider == "mysql" else "",
        "table_name": project.db_table,
        "keyfields": kf_list or [{"id": 0, "name": "", "type": "VARCHAR(255)", "values": ""}],
        "resultfields": rf_list,
        "logtables": lt_list,
        "_nid": nid,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def projects_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    projects = await state.project_registry.get_all()
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={
            "projects": projects,
            "current_path": str(Path.cwd()),
        },
    )


@router.post("/switch/{project_id}")
async def switch_project(request: Request, project_id: int):
    state = get_state(request)
    project = await state.project_registry.get_by_id(project_id)
    if not project:
        return {"ok": False, "error": "Project not found"}

    # Prefer loading from original config files when available
    if project.config_path and Path(project.config_path).exists():
        db_config_arg = (
            project.db_config_path
            if project.db_config_path and Path(project.db_config_path).exists()
            else None
        )
        try:
            new_exp_cfg, new_creds = load_config(project.config_path, db_config_arg)
        except Exception as exc:
            return {"ok": False, "error": f"Failed to load config files: {exc}"}
    else:
        # Fall back to serialised snapshot
        cfg_data = project.config_data()
        kf = {k: KeyfieldConfig(type=v) for k, v in cfg_data.get("keyfields", {}).items()}
        table_cfg = TableConfig(
            name=project.db_table,
            keyfields=kf,
            resultfields=cfg_data.get("resultfields", {}),
            logtables=cfg_data.get("logtables", {}),
            result_timestamps=cfg_data.get("result_timestamps", False),
        )
        new_exp_cfg = ExperimenterConfig(database=project.db_database, table=table_cfg)
        new_creds = CredentialsConfig(
            server=project.db_host,
            port=project.db_port,
            user=project.db_user,
            password=project.db_password,
            database=project.db_database,
        )

    try:
        await _activate_state(
            request, new_exp_cfg, new_creds,
            Path(project.workspace_db), project.config_path, project.db_config_path,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "name": project.name, "table": project.db_table}


@router.get("/new", response_class=HTMLResponse)
async def config_editor_page(request: Request) -> HTMLResponse:
    templates = get_templates(request)
    return templates.TemplateResponse(request=request, name="config_editor.html", context={"edit_data": None})


@router.get("/{project_id}/edit", response_class=HTMLResponse)
async def edit_config_page(request: Request, project_id: int) -> HTMLResponse:
    state = get_state(request)
    project = await state.project_registry.get_by_id(project_id)
    if not project:
        return RedirectResponse("/projects", status_code=302)
    templates = get_templates(request)
    edit_data = _build_edit_data(project)
    return templates.TemplateResponse(
        request=request,
        name="config_editor.html",
        context={"edit_data": edit_data},
    )


@router.post("/generate-config")
async def generate_config(request: Request) -> JSONResponse:
    """Generate YAML content from form data and return for preview / download."""
    body: dict[str, Any] = await request.json()
    try:
        config_yaml, db_config_yaml = _build_yaml_content(body)
        return JSONResponse({"config_yaml": config_yaml, "db_config_yaml": db_config_yaml})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/save-config")
async def save_config(request: Request) -> JSONResponse:
    """Write workspace files, register project, and activate it."""
    body: dict[str, Any] = await request.json()
    try:
        config_yaml_str, db_config_yaml_str = _build_yaml_content(body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    try:
        table_name = (body.get("table_name") or "").strip()
        workspace_dir = _WORKSPACES_DIR / table_name
        workspace_dir.mkdir(parents=True, exist_ok=True)

        config_path = workspace_dir / "config.yml"
        config_path.write_text(config_yaml_str, encoding="utf-8")

        db_config_path: Path | None = None
        if db_config_yaml_str:
            db_config_path = workspace_dir / "db_config.yml"
            db_config_path.write_text(db_config_yaml_str, encoding="utf-8")

        workspace_db = workspace_dir / "query_history.sqlite"

        new_exp_cfg, new_creds = load_config(
            str(config_path),
            str(db_config_path) if db_config_path else None,
        )

        state = get_state(request)
        await state.project_registry.register(
            path=str(workspace_dir),
            workspace_db=str(workspace_db),
            db_host=new_creds.server if new_creds else "",
            db_port=new_creds.port if new_creds else 0,
            db_user=new_creds.user if new_creds else "",
            db_password=new_creds.password if new_creds else "",
            db_database=new_creds.database if new_creds else (new_exp_cfg.sqlite_path or ""),
            db_table=new_exp_cfg.table.name,
            config_path=str(config_path),
            db_config_path=str(db_config_path) if db_config_path else "",
            config_json=json.dumps({
                "keyfields": {k: v.type for k, v in new_exp_cfg.table.keyfields.items()},
                "resultfields": dict(new_exp_cfg.table.resultfields),
                "logtables": {lt: dict(cols) for lt, cols in new_exp_cfg.table.logtables.items()},
                "result_timestamps": new_exp_cfg.table.result_timestamps,
            }),
        )

        try:
            await _activate_state(
                request, new_exp_cfg, new_creds,
                workspace_db, str(config_path),
                str(db_config_path) if db_config_path else "",
            )
        except Exception as exc:
            return JSONResponse(
                {"error": f"Config saved and registered, but DB connection failed: {exc}"},
                status_code=422,
            )

        return JSONResponse({"ok": True})

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/upload")
async def upload_config(
    request: Request,
    config_file: UploadFile = File(...),
    db_config_file: Optional[UploadFile] = File(None),
):
    """Accept uploaded config.yml (+ optional db_config.yml for MySQL), create a home-dir workspace, and activate."""
    state = get_state(request)

    config_bytes = await config_file.read()
    db_config_bytes = await db_config_file.read() if db_config_file else None

    with tempfile.TemporaryDirectory() as tmp:
        cfg_tmp = Path(tmp) / "config.yml"
        cfg_tmp.write_bytes(config_bytes)

        db_tmp: Path | None = None
        if db_config_bytes:
            db_tmp = Path(tmp) / "db_config.yml"
            db_tmp.write_bytes(db_config_bytes)

        try:
            new_exp_cfg, new_creds = load_config(str(cfg_tmp), str(db_tmp) if db_tmp else None)
        except Exception as exc:
            templates = get_templates(request)
            projects = await state.project_registry.get_all()
            return templates.TemplateResponse(
                request=request,
                name="projects.html",
                context={
                    "projects": projects,
                    "current_path": str(Path.cwd()),
                    "upload_error": f"Failed to parse config files: {exc}",
                },
                status_code=422,
            )

    workspace_dir = _WORKSPACES_DIR / new_exp_cfg.table.name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    config_path = workspace_dir / "config.yml"
    config_path.write_bytes(config_bytes)

    db_config_path: Path | None = None
    if db_config_bytes:
        db_config_path = workspace_dir / "db_config.yml"
        db_config_path.write_bytes(db_config_bytes)

    workspace_db = workspace_dir / "query_history.sqlite"

    await state.project_registry.register(
        path=str(workspace_dir),
        workspace_db=str(workspace_db),
        db_host=new_creds.server if new_creds else "",
        db_port=new_creds.port if new_creds else 0,
        db_user=new_creds.user if new_creds else "",
        db_password=new_creds.password if new_creds else "",
        db_database=new_creds.database if new_creds else (new_exp_cfg.sqlite_path or ""),
        db_table=new_exp_cfg.table.name,
        config_path=str(config_path),
        db_config_path=str(db_config_path) if db_config_path else "",
        config_json=json.dumps({
            "keyfields": {k: v.type for k, v in new_exp_cfg.table.keyfields.items()},
            "resultfields": dict(new_exp_cfg.table.resultfields),
            "logtables": {lt: dict(cols) for lt, cols in new_exp_cfg.table.logtables.items()},
            "result_timestamps": new_exp_cfg.table.result_timestamps,
        }),
    )

    try:
        await _activate_state(
            request, new_exp_cfg, new_creds,
            workspace_db, str(config_path),
            str(db_config_path) if db_config_path else "",
        )
    except Exception as exc:
        templates = get_templates(request)
        projects = await state.project_registry.get_all()
        return templates.TemplateResponse(
            request=request,
            name="projects.html",
            context={
                "projects": projects,
                "current_path": str(Path.cwd()),
                "upload_error": f"Config parsed but DB connection failed: {exc}",
            },
            status_code=422,
        )

    return RedirectResponse("/", status_code=303)
