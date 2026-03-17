"""Experiments router: table view and detail view."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from py_experimenter_db.dashboard.app import get_state, get_templates, is_htmx
from py_experimenter_db.db.queries import (
    get_experiment_detail,
    get_experiments_page,
    get_keyfield_distinct_values,
    get_logtable_rows,
)
from py_experimenter_db.db.schema import STANDARD_COLUMNS

router = APIRouter(prefix="/experiments")

def _parse_columns(request: Request, schema_all_cols: list[str]) -> list[str]:
    """Get column selection from query param, cookie, or configured default."""
    raw = request.query_params.getlist("columns")
    if raw:
        cols = [c for c in raw if c in schema_all_cols]
        if cols:
            return cols
    # Try cookie
    cookie_val = request.cookies.get("exp_columns")
    if cookie_val:
        try:
            cols = [c for c in json.loads(cookie_val) if c in schema_all_cols]
            if cols:
                return cols
        except Exception:
            pass
    # Fall back to configured default
    state = get_state(request)
    return [c for c in state.settings.default_columns if c in schema_all_cols]


@router.get("", response_class=HTMLResponse)
async def experiments_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    kf_values = await get_keyfield_distinct_values(state.pool, state.schema)
    selected_cols = _parse_columns(request, state.schema.all_columns)
    return templates.TemplateResponse(
        request=request,
        name="experiments.html",
        context={
            "kf_values": kf_values,
            "selected_cols": selected_cols,
            "all_columns": state.schema.all_columns,
            "default_sort_col": state.settings.default_sort_col,
            "default_sort_dir": state.settings.default_sort_dir,
        },
    )


@router.get("/table", response_class=HTMLResponse)
async def experiments_table(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    params = request.query_params

    selected_cols = _parse_columns(request, state.schema.all_columns)

    page_obj = await get_experiments_page(
        pool=state.pool,
        schema=state.schema,
        columns=selected_cols,
        page=int(params.get("page", 1)),
        page_size=int(params.get("page_size", state.settings.default_page_size)),
        sort_col=params.get("sort", state.settings.default_sort_col),
        sort_dir=params.get("dir", state.settings.default_sort_dir),
        search=params.get("search") or None,
        status_filter=params.getlist("status") or None,
        keyfield_filters={
            kf: params.get(f"kf_{kf}", "")
            for kf in state.schema.keyfields
            if params.get(f"kf_{kf}")
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/experiment_table.html",
        context={
            "page": page_obj,
            "selected_cols": selected_cols,
            "sort": params.get("sort", "ID"),
            "dir": params.get("dir", "DESC"),
            "search": params.get("search", ""),
            "status_filter": params.getlist("status"),
        },
    )


@router.get("/{experiment_id}", response_class=HTMLResponse)
async def experiment_detail(request: Request, experiment_id: int) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)

    experiment = await get_experiment_detail(state.pool, state.schema, experiment_id)
    if experiment is None:
        return HTMLResponse(content="Experiment not found", status_code=404)

    # Load logtable data for charts
    logtable_data: dict[str, list[dict[str, Any]]] = {}
    for lt_name in state.schema.logtable_names:
        rows = await get_logtable_rows(state.pool, state.schema, experiment_id, lt_name)
        logtable_data[lt_name] = rows

    # Identify numeric columns per logtable for charting
    logtable_numeric_cols: dict[str, list[str]] = {}
    for lt_name, rows in logtable_data.items():
        if rows:
            numeric = [
                k for k, v in rows[0].items()
                if k not in ("ID", "experiment_id") and isinstance(v, (int, float))
            ]
            logtable_numeric_cols[lt_name] = numeric
        else:
            logtable_numeric_cols[lt_name] = list(state.schema.logtable_columns.get(lt_name, []))

    # Separate keyfield and resultfield values for display
    keyfield_vals = {k: experiment.get(k) for k in state.schema.keyfields}
    resultfield_vals = {k: experiment.get(k) for k in state.schema.resultfields}

    return templates.TemplateResponse(
        request=request,
        name="experiment_detail.html",
        context={
            "experiment": experiment,
            "keyfield_vals": keyfield_vals,
            "resultfield_vals": resultfield_vals,
            "logtable_data": logtable_data,
            "logtable_numeric_cols": logtable_numeric_cols,
            "exception_column": state.schema.exception_column,
        },
    )
