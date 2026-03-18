"""Chat router: LLM-assisted data analysis with executable code generation."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from py_experimenter_db.dashboard.app import get_state, get_templates
from py_experimenter_db.dashboard.code_runner import run_code
from py_experimenter_db.dashboard.llm import chat_completion
from py_experimenter_db.db.queries import TableSchema, get_db_schema
from py_experimenter_db.db.schema import SchemaInfo

router = APIRouter(prefix="/chat")

# ── Pydantic request models ────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    session_id: int
    messages: list[Message]


class ExecuteRequest(BaseModel):
    code: str


class CreateSessionRequest(BaseModel):
    name: str


class RenameSessionRequest(BaseModel):
    name: str


class SetMemoryRequest(BaseModel):
    content: str


class SaveScriptRequest(BaseModel):
    name: str
    content: str


# ── Helpers ────────────────────────────────────────────────────────────────────

_SAFE_FILENAME = re.compile(r"^[\w\-. ]+$")
_UPDATE_MEMORY_RE = re.compile(r"<update_memory>([\s\S]*?)</update_memory>", re.IGNORECASE)


def _output_dir(state) -> Path:
    d = state.history_db_path.parent / "chat_outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_output_path(state, filename: str) -> Path:
    if not _SAFE_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    base = _output_dir(state).resolve()
    path = (base / filename).resolve()
    if not str(path).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return path


def _build_system_prompt(
    schema: SchemaInfo,
    db_schema: list[TableSchema],
    mental_state: str = "",
    global_memory: str = "",
) -> str:
    lines = [
        "You are a data analysis assistant for PyExperimenter, a Python framework for ML experiments.",
        "",
        "=== Database Schema ===",
        f"Main table: `{schema.table_name}`",
        "  Standard columns: ID, status, machine, creation_date, start_date, end_date",
    ]
    if schema.exception_column:
        lines.append(f"  Exception/traceback column: {schema.exception_column}")
    lines.append(f"  Keyfields (experiment parameters): {', '.join(schema.keyfields) or '(none)'}")
    lines.append(f"  Result fields: {', '.join(schema.resultfields) or '(none)'}")

    logtables = [t for t in db_schema if t.label.startswith("Logtable:")]
    if logtables:
        lines.append("")
        lines.append("Log tables (use the exact DB table name shown in SQL queries):")
        for tbl in logtables:
            non_meta = [c.name for c in tbl.columns if c.name not in ("ID", "experiment_id")]
            lines.append(f"  `{tbl.table_name}` — columns: {', '.join(non_meta)}")
            lines.append(f"    Join hint: {tbl.table_name}.experiment_id = {schema.table_name}.ID")

    cc = next((t for t in db_schema if t.label == "CodeCarbon"), None)
    if cc:
        lines.append("")
        cc_cols = [c.name for c in cc.columns if c.name not in ("ID", "experiment_id")]
        lines.append(f"CodeCarbon table: `{cc.table_name}` — columns: {', '.join(cc_cols)}")

    lines += [
        "",
        "=== Execution Environment ===",
        "The generated code runs in a Python subprocess with these pre-imported symbols:",
        "  query(sql, **kw) -> pd.DataFrame   # query the MySQL database",
        "  pd                                  # pandas",
        "  np                                  # numpy",
        "  plt                                 # matplotlib.pyplot (Agg backend)",
        f"  TABLE        = {schema.table_name!r}",
        f"  KEYFIELDS    = {schema.keyfields!r}",
        f"  RESULTFIELDS = {schema.resultfields!r}",
        f"  LOGTABLES    = {{db_table_name: [columns], ...}}  # {len(logtables)} logtable(s)",
        "",
        "  Calling plt.show() automatically saves the figure as a PNG and shows it in the UI.",
        "  Use print() to output text — it will appear below the code editor.",
        "",
        "=== Instructions ===",
        "1. If the user's request is ambiguous, ask ONE focused clarifying question BEFORE generating code.",
        "2. When generating code, wrap it in ```python ... ``` blocks.",
        "3. Annotate the code with brief comments explaining each step.",
        "4. For aggregations prefer SQL GROUP BY or pandas groupby/agg over raw loops.",
        "5. For visualizations use descriptive titles, axis labels, and legends.",
        "6. You may produce multiple code blocks for multi-step analyses.",
        "7. After the code, briefly describe what it does and what the output represents.",
        "8. Whenever you learn something important about the user's data, experiments, or goals,",
        "   include an <update_memory> block at the end of your response with a concise markdown",
        "   summary of what you want to remember for future sessions. Example:",
        "   <update_memory>",
        "   - Main experiment compares 3 optimizers (Adam, SGD, RMSprop) across 5 learning rates.",
        "   - User prefers bar charts over line charts for categorical comparisons.",
        "   </update_memory>",
        "   Only emit this block when there is genuinely new information worth remembering.",
    ]

    if mental_state:
        lines = [
            "=== Assistant Memory (from prior sessions) ===",
            mental_state.strip(),
            "",
        ] + lines

    if global_memory:
        lines = [
            "=== Cross-Project Knowledge (from global memory) ===",
            global_memory.strip(),
            "",
        ] + lines

    return "\n".join(lines)


def _extract_code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:python)?\n([\s\S]*?)```", text)


def _strip_memory_tags(text: str) -> str:
    """Remove <update_memory>...</update_memory> from the visible reply."""
    return _UPDATE_MEMORY_RE.sub("", text).strip()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    state = get_state(request)
    templates = get_templates(request)
    sessions = await state.history_store.get_sessions()
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "schema": state.schema,
            "llm_configured": bool(state.settings.llm_url),
            "sessions": [{"id": s.id, "name": s.name} for s in sessions],
        },
    )


# ── Session endpoints ──────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(request: Request):
    state = get_state(request)
    sessions = await state.history_store.get_sessions()
    return [{"id": s.id, "name": s.name, "updated_at": s.updated_at} for s in sessions]


@router.post("/sessions")
async def create_session(request: Request, body: CreateSessionRequest):
    state = get_state(request)
    session = await state.history_store.create_session(body.name)
    return {"id": session.id, "name": session.name, "updated_at": session.updated_at}


@router.put("/sessions/{session_id}")
async def rename_session(request: Request, session_id: int, body: RenameSessionRequest):
    state = get_state(request)
    await state.history_store.rename_session(session_id, body.name)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: int):
    state = get_state(request)
    await state.history_store.delete_session(session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(request: Request, session_id: int):
    state = get_state(request)
    msgs = await state.history_store.get_messages(session_id)
    return [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at} for m in msgs]


# ── Memory endpoints ───────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory(request: Request):
    state = get_state(request)
    content = await state.history_store.get_mental_state()
    return {"content": content}


@router.put("/memory")
async def set_memory(request: Request, body: SetMemoryRequest):
    state = get_state(request)
    await state.history_store.set_mental_state(body.content)
    return {"ok": True}


@router.get("/global-memory")
async def get_global_memory(request: Request):
    state = get_state(request)
    content = await state.project_registry.get_global_memory()
    return {"content": content}


@router.put("/global-memory")
async def set_global_memory(request: Request, body: SetMemoryRequest):
    state = get_state(request)
    await state.project_registry.set_global_memory(body.content)
    return {"ok": True}


# ── Script endpoints ───────────────────────────────────────────────────────────

@router.get("/scripts")
async def list_scripts(request: Request):
    state = get_state(request)
    scripts = await state.history_store.get_scripts()
    return [{"id": s.id, "name": s.name, "updated_at": s.updated_at} for s in scripts]


@router.post("/scripts")
async def create_script(request: Request, body: SaveScriptRequest):
    state = get_state(request)
    script = await state.history_store.create_script(body.name, body.content)
    return {"id": script.id, "name": script.name, "updated_at": script.updated_at}


@router.put("/scripts/{script_id}")
async def save_script(request: Request, script_id: int, body: SaveScriptRequest):
    state = get_state(request)
    ver = await state.history_store.save_script_version(script_id, body.content)
    if body.name:
        await state.history_store.rename_script(script_id, body.name)
    return {"version_id": ver.id, "created_at": ver.created_at}


@router.get("/scripts/{script_id}/versions")
async def get_script_versions(request: Request, script_id: int):
    state = get_state(request)
    versions = await state.history_store.get_script_versions(script_id)
    return [{"id": v.id, "created_at": v.created_at} for v in versions]


@router.get("/scripts/{script_id}/versions/{version_id}")
async def get_script_version(request: Request, script_id: int, version_id: int):
    state = get_state(request)
    versions = await state.history_store.get_script_versions(script_id)
    ver = next((v for v in versions if v.id == version_id), None)
    if ver is None:
        raise HTTPException(status_code=404)
    return {"id": ver.id, "content": ver.content, "created_at": ver.created_at}


@router.delete("/scripts/{script_id}")
async def delete_script(request: Request, script_id: int):
    state = get_state(request)
    await state.history_store.delete_script(script_id)
    return {"ok": True}


# ── LLM chat ──────────────────────────────────────────────────────────────────

@router.post("/message")
async def chat_message(request: Request, body: ChatRequest):
    state = get_state(request)
    s = state.settings

    # Persist user message first, regardless of LLM availability
    user_content = body.messages[-1].content if body.messages else ""
    if user_content:
        await state.history_store.append_message(body.session_id, "user", user_content)
        await state.history_store.touch_session(body.session_id)

    if not s.llm_url:
        msg = (
            "The LLM connector is not configured. "
            "Please go to the **Configuration** page and add an LLM URL."
        )
        await state.history_store.append_message(body.session_id, "assistant", msg)
        return {
            "content": msg,
            "code": None,
            "filename": None,
            "memory_updated": False,
            "new_memory": None,
        }

    mental_state = await state.history_store.get_mental_state()
    global_memory = await state.project_registry.get_global_memory()
    db_schema = await get_db_schema(state.db, state.schema)
    system_msg = {"role": "system", "content": _build_system_prompt(state.schema, db_schema, mental_state, global_memory)}
    messages = [system_msg] + [{"role": m.role, "content": m.content} for m in body.messages]

    try:
        raw_reply = await chat_completion(
            messages=messages,
            url=s.llm_url,
            token=s.llm_token,
            model=s.llm_model,
        )
    except Exception as exc:
        err_msg = f"LLM request failed: {exc}"
        await state.history_store.append_message(body.session_id, "assistant", err_msg)
        return {
            "content": err_msg,
            "code": None,
            "filename": None,
            "memory_updated": False,
            "new_memory": None,
        }

    # Parse and apply memory updates
    memory_match = _UPDATE_MEMORY_RE.search(raw_reply)
    new_memory: str | None = None
    memory_updated = False
    if memory_match:
        new_memory = memory_match.group(1).strip()
        existing = await state.history_store.get_mental_state()
        updated = (existing.strip() + "\n\n" + new_memory).strip() if existing.strip() else new_memory
        await state.history_store.set_mental_state(updated)
        memory_updated = True

    reply = _strip_memory_tags(raw_reply)

    # Persist assistant message (stripped)
    await state.history_store.append_message(body.session_id, "assistant", reply)

    code_blocks = _extract_code_blocks(reply)
    code: str | None = None
    filename: str | None = None
    if code_blocks:
        code = "\n\n".join(code_blocks)
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        filename = f"analysis_{ts}.py"
        (_output_dir(state) / filename).write_text(code, encoding="utf-8")

    return {
        "content": reply,
        "code": code,
        "filename": filename,
        "memory_updated": memory_updated,
        "new_memory": new_memory,
    }


@router.post("/execute")
async def chat_execute(request: Request, body: ExecuteRequest):
    state = get_state(request)
    result = await run_code(
        code=body.code,
        creds=state.creds,
        schema=state.schema,
        output_dir=_output_dir(state),
        sqlite_path=state.experimenter_config.sqlite_path if state.experimenter_config else None,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "plots": result.plots,
        "error": result.error,
    }


@router.get("/output/{filename}")
async def chat_output(request: Request, filename: str):
    state = get_state(request)
    path = _safe_output_path(state, filename)
    if not path.exists():
        raise HTTPException(status_code=404)
    media = "image/png" if filename.endswith(".png") else "text/html"
    return FileResponse(path, media_type=media)


@router.get("/download/{filename}")
async def chat_download(request: Request, filename: str):
    state = get_state(request)
    path = _safe_output_path(state, filename)
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="text/plain", filename=filename)
