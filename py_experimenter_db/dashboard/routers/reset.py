"""Reset experiments router: filtered search + bulk reset with logtable/codecarbon options."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.db.queries import rerun_experiments, search_experiments_for_reset

router = APIRouter(prefix="/reset")

_ALL_STATUSES = ["created", "running", "done", "error"]


@router.get("", response_class=HTMLResponse)
async def reset_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    return templates.TemplateResponse(
        request=request,
        name="reset.html",
        context={},
    )


@router.post("/preview", response_class=HTMLResponse)
async def reset_preview(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    form = await request.form()

    statuses = [s for s in _ALL_STATUSES if form.get(f"status_{s}")]
    keyfield_filters = {
        kf: str(form.get(f"kf_{kf}", ""))
        for kf in state.schema.keyfields
    }

    candidates = await search_experiments_for_reset(
        state.db, state.schema, statuses, keyfield_filters
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/reset_preview.html",
        context={"candidates": candidates, "keyfields": state.schema.keyfields},
    )


@router.post("/execute", response_class=HTMLResponse)
async def reset_execute(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    form = await request.form()

    ids_raw = form.getlist("ids")
    try:
        ids = [int(i) for i in ids_raw if i]
    except ValueError:
        return HTMLResponse("Invalid IDs", status_code=400)

    delete_logtable = bool(form.get("delete_logtable"))
    delete_codecarbon = bool(form.get("delete_codecarbon"))

    count = await rerun_experiments(
        state.db, state.schema, ids,
        delete_logtable_data=delete_logtable,
        delete_codecarbon=delete_codecarbon,
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/toast.html",
        context={"message": f"Reset {count} experiment(s) to 'created'", "kind": "success"},
    )
