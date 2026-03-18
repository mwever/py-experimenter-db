"""Failure analysis router."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.db.queries import (
    get_experiment_exception,
    get_failure_groups,
    rerun_experiments,
)

router = APIRouter(prefix="/failures")


@router.get("", response_class=HTMLResponse)
async def failures_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    groups = await get_failure_groups(state.db, state.schema)
    return templates.TemplateResponse(
        request=request,
        name="failures.html",
        context={"groups": groups},
    )


@router.get("/exception/{experiment_id}", response_class=HTMLResponse)
async def get_exception(request: Request, experiment_id: int) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    exc = await get_experiment_exception(state.db, state.schema, experiment_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/exception_detail.html",
        context={"experiment_id": experiment_id, "exception": exc or "(no exception recorded)"},
    )


@router.post("/rerun", response_class=HTMLResponse)
async def rerun_selected(
    request: Request,
    delete_logtable: bool = Form(False),
) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    form = await request.form()

    ids_raw = form.getlist("ids")
    try:
        ids = [int(i) for i in ids_raw if i]
    except ValueError:
        return HTMLResponse("Invalid experiment IDs", status_code=400)

    count = await rerun_experiments(state.db, state.schema, ids, delete_logtable_data=delete_logtable)
    return templates.TemplateResponse(
        request=request,
        name="partials/toast.html",
        context={"message": f"Reset {count} experiment(s) to 'created'", "kind": "success"},
    )


@router.post("/rerun-group", response_class=HTMLResponse)
async def rerun_group(
    request: Request,
    delete_logtable: bool = Form(False),
) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    form = await request.form()

    ids_raw = str(form.get("ids", "")).split(",")
    try:
        ids = [int(i.strip()) for i in ids_raw if i.strip()]
    except ValueError:
        return HTMLResponse("Invalid experiment IDs", status_code=400)

    count = await rerun_experiments(state.db, state.schema, ids, delete_logtable_data=delete_logtable)
    return templates.TemplateResponse(
        request=request,
        name="partials/toast.html",
        context={"message": f"Reset {count} experiment(s) to 'created'", "kind": "success"},
    )
