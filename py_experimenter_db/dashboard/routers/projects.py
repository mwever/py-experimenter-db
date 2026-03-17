"""Projects router: multi-project management and workspace switching."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from py_experimenter_db.config import (
    CredentialsConfig,
    ExperimenterConfig,
    KeyfieldConfig,
    TableConfig,
    load_config,
)
from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.dashboard.settings import settings_from_db
from py_experimenter_db.db.connection import create_pool
from py_experimenter_db.db.schema import build_schema_info
from py_experimenter_db.history.store import QueryHistoryStore

router = APIRouter(prefix="/projects")


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

    # Prefer loading directly from the original config files when available
    if project.config_path and project.db_config_path and \
            Path(project.config_path).exists() and Path(project.db_config_path).exists():
        try:
            new_exp_cfg, new_creds = load_config(project.config_path, project.db_config_path)
        except Exception as exc:
            return {"ok": False, "error": f"Failed to load config files: {exc}"}
    else:
        # Fall back to the serialised snapshot stored in the DB
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

    # Connect to new DB
    try:
        new_pool = await create_pool(new_creds)
        new_schema = await build_schema_info(new_exp_cfg, new_pool)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # Load new workspace store
    new_workspace = Path(project.workspace_db)
    new_store = QueryHistoryStore(new_workspace)
    await new_store.init()
    raw_settings = await new_store.get_all_settings()
    new_settings = settings_from_db(raw_settings)

    # Atomically swap app state
    old_pool = state.pool
    state.pool = new_pool
    state.schema = new_schema
    state.creds = new_creds
    state.experimenter_config = new_exp_cfg
    state.history_store = new_store
    state.history_db_path = new_workspace
    state.settings = new_settings
    state.config_path = project.config_path
    state.db_config_path = project.db_config_path

    # Update template globals so every subsequent render reflects the new project
    env = request.app.state.templates.env
    env.globals["table_name"] = new_schema.table_name
    env.globals["keyfields"] = new_schema.keyfields
    env.globals["resultfields"] = new_schema.resultfields
    env.globals["has_codecarbon"] = new_schema.has_codecarbon

    old_pool.close()
    await old_pool.wait_closed()

    return {"ok": True, "name": project.name, "table": project.db_table}
