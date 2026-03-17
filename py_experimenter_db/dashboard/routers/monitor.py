"""Monitor router: experiment stats and worker overview."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.db.queries import get_monitor_stats, get_workers

router = APIRouter()


def _read_yaml_file(path: str) -> str | None:
    """Return file contents, or None if path is empty / file missing."""
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


@router.get("/", response_class=HTMLResponse)
async def monitor_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    stats = await get_monitor_stats(state.pool, state.schema)
    workers = await get_workers(state.pool, state.schema)
    return templates.TemplateResponse(
        request=request,
        name="monitor.html",
        context={
            "stats": stats,
            "workers": workers,
            "config_yaml": _read_yaml_file(state.config_path),
            "db_config_yaml": _read_yaml_file(state.db_config_path),
            "config_path": state.config_path,
            "db_config_path": state.db_config_path,
        },
    )


@router.get("/api/stats", response_class=HTMLResponse)
async def stats_fragment(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    stats = await get_monitor_stats(state.pool, state.schema)
    return templates.TemplateResponse(
        request=request,
        name="partials/stats_bar.html",
        context={"stats": stats},
    )


@router.get("/api/workers", response_class=HTMLResponse)
async def workers_fragment(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    workers = await get_workers(state.pool, state.schema)
    return templates.TemplateResponse(
        request=request,
        name="partials/worker_list.html",
        context={"workers": workers},
    )
