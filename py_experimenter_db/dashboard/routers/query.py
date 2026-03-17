"""SQL Query Tool router."""

from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.db.queries import execute_query, get_db_schema

router = APIRouter(prefix="/query")


@router.get("", response_class=HTMLResponse)
async def query_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    history = await state.history_store.get_history(50)
    saved = await state.history_store.get_saved_queries()
    db_schema = await get_db_schema(state.pool, state.schema)
    hints_tables = {tbl.table_name: [col.name for col in tbl.columns] for tbl in db_schema}
    return templates.TemplateResponse(
        request=request,
        name="query.html",
        context={
            "history": history,
            "saved": saved,
            "initial_sql": "",
            "db_schema": db_schema,
            "hints_tables": hints_tables,
        },
    )


@router.post("/execute", response_class=HTMLResponse)
async def execute(request: Request, sql: str = Form(...)) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)

    t0 = time.monotonic()
    result = await execute_query(state.pool, sql)
    duration_ms = int((time.monotonic() - t0) * 1000)

    # Store in history
    await state.history_store.add_to_history(
        sql_text=sql,
        row_count=result.row_count if not result.error else None,
        duration_ms=duration_ms,
        error=result.error,
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/query_results.html",
        context={"result": result, "sql": sql, "duration_ms": duration_ms},
    )


@router.get("/history", response_class=HTMLResponse)
async def history_fragment(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    history = await state.history_store.get_history(50)
    return templates.TemplateResponse(
        request=request,
        name="partials/query_history.html",
        context={"history": history},
    )


@router.post("/save", response_class=HTMLResponse)
async def save_query(
    request: Request,
    name: str = Form(...),
    sql: str = Form(...),
) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    await state.history_store.save_query(name=name, sql_text=sql)
    saved = await state.history_store.get_saved_queries()
    return templates.TemplateResponse(
        request=request,
        name="partials/saved_queries.html",
        context={"saved": saved},
    )


@router.delete("/saved/{query_id}", response_class=HTMLResponse)
async def delete_saved(request: Request, query_id: int) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    await state.history_store.delete_saved_query(query_id)
    saved = await state.history_store.get_saved_queries()
    return templates.TemplateResponse(
        request=request,
        name="partials/saved_queries.html",
        context={"saved": saved},
    )


@router.get("/saved/{query_id}")
async def get_saved(request: Request, query_id: int) -> JSONResponse:
    state = get_state(request)
    sq = await state.history_store.get_saved_query(query_id)
    if sq is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({"sql": sq.sql_text, "name": sq.name})
