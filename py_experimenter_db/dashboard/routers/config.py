"""Configuration page router."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from py_experimenter_db.dashboard.app import get_state, get_templates, reload_settings
from py_experimenter_db.dashboard.settings import settings_to_db

router = APIRouter(prefix="/config")


@router.get("", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"all_columns": state.schema.all_columns},
    )


@router.post("", response_class=HTMLResponse)
async def save_config(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    form = await request.form()

    s = state.settings

    # Refresh interval
    try:
        s.ui_refresh_interval = max(1, int(form.get("ui_refresh_interval", s.ui_refresh_interval)))
    except (ValueError, TypeError):
        pass

    # Default columns (multi-value checkbox list)
    cols = form.getlist("default_columns")
    if cols:
        s.default_columns = [c for c in cols if c in state.schema.all_columns]

    # Page size
    try:
        s.default_page_size = max(10, min(500, int(form.get("default_page_size", s.default_page_size))))
    except (ValueError, TypeError):
        pass

    # Sort column / direction
    sort_col = str(form.get("default_sort_col", s.default_sort_col))
    if sort_col in state.schema.all_columns:
        s.default_sort_col = sort_col
    sort_dir = str(form.get("default_sort_dir", s.default_sort_dir))
    if sort_dir in ("ASC", "DESC"):
        s.default_sort_dir = sort_dir

    # LLM connector
    s.llm_url = str(form.get("llm_url", s.llm_url)).strip()
    s.llm_token = str(form.get("llm_token", s.llm_token)).strip()
    s.llm_model = str(form.get("llm_model", s.llm_model)).strip() or "gpt-4o"

    await state.history_store.set_settings(settings_to_db(s))
    await reload_settings(request)

    return templates.TemplateResponse(
        request=request,
        name="partials/toast.html",
        context={"message": "Settings saved", "kind": "success"},
    )
