"""Carbon footprint router."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.db.queries import get_carbon_summary, get_carbon_timeseries

router = APIRouter(prefix="/carbon")


@router.get("", response_class=HTMLResponse)
async def carbon_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)

    if not state.schema.has_codecarbon:
        return templates.TemplateResponse(
            request=request,
            name="carbon.html",
            context={"summary": None, "timeseries": []},
        )

    summary = await get_carbon_summary(state.db, state.schema)
    timeseries = await get_carbon_timeseries(state.db, state.schema)

    return templates.TemplateResponse(
        request=request,
        name="carbon.html",
        context={"summary": summary, "timeseries": timeseries},
    )
