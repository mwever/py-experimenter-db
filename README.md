# PyExperimenter Dashboard

[![Release](https://img.shields.io/github/v/release/mwever/py-experimenter-dashboard)](https://img.shields.io/github/v/release/mwever/py-experimenter-dashboard)
[![Build status](https://img.shields.io/github/actions/workflow/status/mwever/py-experimenter-dashboard/main.yml?branch=main)](https://github.com/mwever/py-experimenter-dashboard/actions/workflows/main.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/mwever/py-experimenter-dashboard/branch/main/graph/badge.svg)](https://codecov.io/gh/mwever/py-experimenter-dashboard)
[![License](https://img.shields.io/github/license/mwever/py-experimenter-dashboard)](https://img.shields.io/github/license/mwever/py-experimenter-dashboard)

A web-based dashboard for monitoring, managing, and post-processing experiments run with [PyExperimenter](https://github.com/tornede/py_experimenter). Supports both **MySQL** and **SQLite** backends. Connect it to your existing PyExperimenter database and get a live cockpit for your experiment runs — no additional infrastructure required.

- **Github repository**: <https://github.com/mwever/py-experimenter-dashboard/>
- **Documentation**: <https://mwever.github.io/py-experimenter-dashboard/>

---

## Features

| Section | Description |
|---|---|
| **Monitor** | Live stats (total / done / running / pending / failed), progress bar, average runtime and ETA — auto-refreshed. Active workers and config YAML files (with syntax highlighting and collapsible subtrees) shown side by side. |
| **Experiments** | Searchable, filterable, sortable, paginated table of all experiments. Filter by status, keyfields, or free text. Toggle visible columns. Click any row to open the full detail view. |
| **Experiment Detail** | Full view of a single experiment — key parameters, result fields, timing, worker. Log table entries rendered as interactive Plotly charts (one chart per log table). |
| **Failure Analysis** | Failed experiments grouped by the last line of their stack trace. Expand groups to inspect sample tracebacks. |
| **Reset Experiments** | Filter by status and keyfield values (exact, multi-value list, numeric range, comparison, wildcard), preview matching experiments in a checkboxed table, untick individual rows, choose whether to delete associated log table and/or CodeCarbon data, then confirm. |
| **SQL Query Tool** | CodeMirror-powered SQL editor with syntax highlighting, auto-complete for table and column names, and Ctrl+Enter to run. Query history persisted locally. Save and reload named queries. |
| **Chat** | LLM-powered assistant with persistent sessions, per-session memory, and a built-in Python script editor. Scripts can call `query(sql)` to read from the experiment database and produce Pandas DataFrames. Output (stdout, stderr, plots) shown inline. Cross-project knowledge stored as global memory. |
| **Carbon Footprint** | If [CodeCarbon](https://mlco2.github.io/codecarbon/) is enabled, summarises total CO₂ emissions, energy consumption, and renders time-series and per-experiment breakdown charts. |
| **Projects** | Global registry of all past projects. Switch between projects without restarting. Upload config files directly in the browser to register new projects. Create new PyExperimenter configurations from scratch using a step-by-step wizard and download the generated YAML files. |
| **Config** | Dashboard settings: live-update interval, default experiment table columns/sorting, and LLM backend (URL, model, API token). LLM defaults can be pre-set via environment variables. |

---

## Requirements

- Python ≥ 3.10
- A PyExperimenter experiment database — either:
  - **MySQL**: running server + `config.yml` + `db_config.yml`
  - **SQLite**: local `.db` file + `config.yml` (no credentials file needed)

---

## Installation

```bash
pip install py-experimenter-dashboard
```

Or, for development directly from the repository:

```bash
git clone https://github.com/mwever/py-experimenter-dashboard.git
cd py-experimenter-dashboard
make install   # creates venv via uv and installs pre-commit hooks
```

---

## Configuration files

The dashboard reads the same YAML files that PyExperimenter uses.

### SQLite project

Only `config.yml` is needed — set `provider: sqlite` and point `database` at the `.db` file (relative to the config file):

```yaml
PY_EXPERIMENTER:
  Database:
    provider: sqlite
    database: experiments.db
    table:
      name: my_experiments
      keyfields:
        learning_rate:
          type: FLOAT
          values: [0.001, 0.01, 0.1]
        seed:
          type: INT
          values: [0, 1, 2, 3, 4]
      resultfields:
        accuracy: FLOAT
        loss:     FLOAT
      logtables:
        training_log:
          epoch:      INT
          train_loss: FLOAT
          val_loss:   FLOAT
```

### MySQL project

Both files are required.

**`config.yml`:**

```yaml
PY_EXPERIMENTER:
  Database:
    provider: mysql
    database: my_experiment_db
    table:
      name: my_experiments
      keyfields:
        learning_rate:
          type: FLOAT
          values: [0.001, 0.01, 0.1]
        seed:
          type: INT
          values: [0, 1, 2, 3, 4]
      resultfields:
        accuracy: FLOAT
        loss:     FLOAT
      logtables:
        training_log:
          epoch:      INT
          train_loss: FLOAT
          val_loss:   FLOAT
```

**`db_config.yml`:**

```yaml
CREDENTIALS:
  Database:
    user: myuser
    password: mypassword
  Connection:
    Standard:
      server: 127.0.0.1
      port: 3306
```

---

## Usage

### Command line

```bash
# MySQL — both files required
py-experimenter-dashboard \
    --config path/to/config.yml \
    --db-config path/to/db_config.yml

# SQLite — config only
py-experimenter-dashboard --config path/to/config.yml

# Project-picker mode — no config needed; select or upload a project in the browser
py-experimenter-dashboard
```

Then open `http://localhost:8080` in your browser.

**All options:**

| Flag | Default | Description |
|---|---|---|
| `--config` | *(optional)* | Path to PyExperimenter `config.yml` |
| `--db-config` | *(optional)* | Path to `db_config.yml` (MySQL only) |
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8080` | Port |
| `--reload` | off | Enable auto-reload (development only) |

When launched without `--config` the dashboard starts in **project-picker mode**: the Projects page is shown first so you can select a previously registered project or upload config files to connect a new one.

### Make targets (development)

```bash
make dev        # launch with example/ configs, auto-reload, localhost only
make run        # launch with overridable defaults
                #   CONFIG=... DB_CONFIG=... HOST=... PORT=... make run
make install    # set up virtual environment and pre-commit hooks
make test       # run test suite
make check      # lint, type-check, dependency audit
```

---

## LLM backend environment variables

The Chat assistant supports any OpenAI-compatible API. The three LLM settings can be pre-configured via environment variables so they do not need to be entered in the browser UI. Values saved via the Config page take precedence; clearing a saved value falls back to the environment variable.

| Variable | Description | Example |
|---|---|---|
| `PY_EXP_LLM_URL` | API base URL | `https://api.openai.com/v1` |
| `PY_EXP_LLM_MODEL` | Model name | `gpt-4o` |
| `PY_EXP_LLM_TOKEN` | API token / bearer token | `sk-…` |

Local inference servers also work (Ollama, LM Studio, vLLM, …):

```bash
export PY_EXP_LLM_URL=http://localhost:11434/v1
export PY_EXP_LLM_MODEL=llama3.2
py-experimenter-dashboard --config config.yml
```

---

## Reset Experiments — filter syntax

The Reset page accepts flexible filter expressions for keyfields:

| Expression | Meaning |
|---|---|
| `foo` | Exact match: `= 'foo'` |
| `a, b, c` | Multiple values: `IN ('a', 'b', 'c')` |
| `1-10` | Numeric range: `BETWEEN 1 AND 10` |
| `>=5` | Comparison: `>= 5` (also `<=`, `>`, `<`, `!=`) |
| `*foo*` | Wildcard: `LIKE '%foo%'` |

---

## Chat — built-in Python scripting

The Chat section provides an LLM assistant aware of your experiment schema, keyfields, result fields, and recent query history.

Scripts have access to a `query(sql)` helper that returns a Pandas DataFrame:

```python
df = query("""
    SELECT learning_rate, AVG(accuracy) as acc
    FROM my_experiments
    WHERE status = 'done'
    GROUP BY learning_rate
""")
print(df)
```

Matplotlib figures are captured and displayed inline. stdout and stderr appear in collapsible panels. Sessions and history are stored persistently in the local workspace SQLite database.

---

## Creating new configurations

The **Projects** page includes a step-by-step configuration wizard (**New Config** button) for creating a fresh PyExperimenter setup without writing YAML by hand:

1. **Provider** — choose SQLite or MySQL
2. **Database** — file path (SQLite) or server credentials (MySQL)
3. **Table & Fields** — table name, keyfields with types and values, resultfields, logtables with columns
4. **Preview & Save** — review the generated YAML, download the files, and optionally save the project directly to the dashboard workspace to activate it immediately

Existing projects can be edited via the **Edit** button on their project card, which pre-populates the wizard with the current configuration and lets you change any field including the database provider.

---

## Local persistence

All workspace-local data (query history, saved queries, chat sessions, settings) is stored in a SQLite database:

```
# For projects launched via CLI:
.py_experimenter_dashboard/
└── query_history.sqlite

# For projects uploaded or created via the wizard:
~/.py_experimenter_dashboard/workspaces/<table_name>/
├── config.yml
├── db_config.yml          # MySQL only
└── query_history.sqlite
```

A global registry tracks all projects ever opened with the dashboard:

```
~/.py_experimenter_dashboard/
├── projects.db            # global project registry + cross-project Chat memory
```

---

## Project structure

```
py_experimenter_db/
├── config.py                  # YAML config parsers (MySQL + SQLite)
├── cli.py                     # CLI entry point
├── __main__.py                # python -m py_experimenter_db support
├── db/
│   ├── connection.py          # DbBackend abstraction (aiomysql + aiosqlite)
│   ├── schema.py              # live DB introspection + SchemaInfo
│   └── queries.py             # all SQL query functions
├── history/
│   └── store.py               # SQLite persistence (aiosqlite)
└── dashboard/
    ├── app.py                 # FastAPI application factory
    ├── state.py               # AppState dataclass
    ├── settings.py            # dashboard settings model
    ├── project_registry.py    # global project registry
    ├── code_runner.py         # sandboxed Python script execution
    ├── llm.py                 # LLM API client (OpenAI-compatible)
    ├── routers/               # one module per dashboard section
    │   ├── monitor.py
    │   ├── experiments.py
    │   ├── failures.py
    │   ├── reset.py
    │   ├── query.py
    │   ├── chat.py
    │   ├── carbon.py
    │   ├── config.py
    │   └── projects.py
    ├── static/
    │   └── logo.png
    └── templates/             # Jinja2 templates
        ├── base.html
        ├── monitor.html
        ├── experiments.html
        ├── experiment_detail.html
        ├── failures.html
        ├── reset.html
        ├── query.html
        ├── chat.html
        ├── carbon.html
        ├── config.html
        ├── config_editor.html
        ├── projects.html
        └── partials/          # HTMX fragment templates
```

**Tech stack** — all frontend assets loaded from CDN, no build step required:

| Library | Purpose |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | Async Python web framework |
| [Jinja2](https://jinja.palletsprojects.com/) | Server-side HTML templating |
| [HTMX](https://htmx.org/) | Live updates and partial page swaps |
| [Alpine.js](https://alpinejs.dev/) | Lightweight client-side state |
| [Tailwind CSS](https://tailwindcss.com/) + [DaisyUI 4](https://daisyui.com/) | Styling |
| [Plotly.js](https://plotly.com/javascript/) | Interactive charts (log tables, carbon) |
| [CodeMirror 5](https://codemirror.net/5/) | SQL and YAML editors with syntax highlighting, folding, autocomplete |
| [aiomysql](https://aiomysql.readthedocs.io/) | Async MySQL driver |
| [aiosqlite](https://aiosqlite.omnilib.dev/) | Async SQLite (local persistence) |

---

## Releasing a new version

- Create an API Token on [PyPI](https://pypi.org/).
- Add the token to your repository secrets as `PYPI_TOKEN` on the [Actions secrets page](https://github.com/mwever/py-experimenter-dashboard/settings/secrets/actions/new).
- Create a [new release](https://github.com/mwever/py-experimenter-dashboard/releases/new) on GitHub with a tag in the form `*.*.*`.

---

Repository scaffolded with [fpgmaas/cookiecutter-uv](https://github.com/fpgmaas/cookiecutter-uv).
