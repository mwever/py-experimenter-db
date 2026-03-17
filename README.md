# PyExperimenter Dashboard

[![Release](https://img.shields.io/github/v/release/mwever/py-experimenter-dashboard)](https://img.shields.io/github/v/release/mwever/py-experimenter-dashboard)
[![Build status](https://img.shields.io/github/actions/workflow/status/mwever/py-experimenter-dashboard/main.yml?branch=main)](https://github.com/mwever/py-experimenter-dashboard/actions/workflows/main.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/mwever/py-experimenter-dashboard/branch/main/graph/badge.svg)](https://codecov.io/gh/mwever/py-experimenter-dashboard)
[![License](https://img.shields.io/github/license/mwever/py-experimenter-dashboard)](https://img.shields.io/github/license/mwever/py-experimenter-dashboard)

A web-based dashboard for monitoring, managing, and post-processing experiments run with [PyExperimenter](https://github.com/tornede/py_experimenter). Connect it to your existing PyExperimenter MySQL database and get a live cockpit for your experiment runs — no additional infrastructure required.

- **Github repository**: <https://github.com/mwever/py-experimenter-dashboard/>
- **Documentation**: <https://mwever.github.io/py-experimenter-dashboard/>

---

## Features

| Section | Description |
|---|---|
| **Monitor** | Live stats (total / done / running / pending / failed), progress bar, average runtime and ETA — auto-refreshed every 5 s. Active workers listed with job count and runtime. Config YAML files rendered with syntax highlighting and collapsible subtrees. |
| **Experiments** | Searchable, filterable, sortable, paginated table of all experiments. Filter by status, keyfields, or free text. Toggle visible columns. Click any row to open the full detail view. |
| **Experiment Detail** | Full view of a single experiment — key parameters, result fields, timing, worker. Log table entries rendered as interactive Plotly charts (one chart per log table). |
| **Failure Analysis** | Failed experiments grouped by the last line of their stack trace. Expand groups to inspect individual traces (lazy-loaded). Reset individual experiments or entire groups with one click, optionally clearing log table data. |
| **Reset Experiments** | Dedicated reset workflow: filter by status and keyfield values (exact, multi-value list, numeric range, comparison, wildcard), preview matching experiments in a checkboxed table, untick individual rows, choose whether to delete associated log table and/or CodeCarbon data, then confirm. |
| **SQL Query Tool** | CodeMirror-powered SQL editor with syntax highlighting, auto-complete for table and column names, and Ctrl+Enter to run. Query history persisted locally (SQLite). Save and reload named queries. |
| **Chat** | LLM-powered assistant (Claude) with persistent sessions, per-session memory, and a built-in Python script editor. Scripts can call `query(sql)` to read from the experiment database and produce Pandas DataFrames. Output (stdout, stderr, plots) shown inline with collapsible sections. Cross-project knowledge stored as global memory. |
| **Carbon Footprint** | If [CodeCarbon](https://mlco2.github.io/codecarbon/) is enabled, summarises total CO₂ emissions, energy consumption, and renders time-series and per-experiment breakdown charts. |
| **Config** | Dashboard settings (LLM model, API key, refresh interval). |
| **Projects** | Global registry of all past dashboard runs (stored in `~/.py_experimenter_dashboard/projects.db`). Switch between projects without restarting — hot-swaps the MySQL connection, schema, and workspace. Shared cross-project memory for the Chat assistant. |

---

## Requirements

- Python ≥ 3.10
- A running MySQL server with an existing PyExperimenter database
- The PyExperimenter `config.yml` and `db_config.yml` for that experiment

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

## Configuration

The dashboard reads the same two YAML files that PyExperimenter uses.

**`config.yml`** — experiment schema (table name, keyfields, result fields, log tables):

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

**`db_config.yml`** — database credentials:

```yaml
CREDENTIALS:
  Database:
    user: myuser
    password: mypassword
  Connection:
    Standard:
      server: 127.0.0.1
      port: 3306          # optional, defaults to 3306
```

---

## Usage

### Command line

```bash
py-experimenter-dashboard \
    --config path/to/config.yml \
    --db-config path/to/db_config.yml \
    --host 0.0.0.0 \
    --port 8080
```

Then open `http://localhost:8080` in your browser.

**All options:**

| Flag | Default | Description |
|---|---|---|
| `--config` | *(required)* | Path to PyExperimenter `config.yml` |
| `--db-config` | *(required)* | Path to PyExperimenter `db_config.yml` |
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8080` | Port |
| `--reload` | off | Enable auto-reload (development only) |

### Make targets (development)

```bash
make dev        # launch with example/ configs, auto-reload, localhost only
make run        # launch with overridable defaults
                #   CONFIG=... DB_CONFIG=... HOST=... PORT=... make run
make install    # set up virtual environment and pre-commit hooks
make test       # run test suite
make check      # lint, type-check, dependency audit
```

### Shell script

```bash
./scripts/dev.sh                               # uses example/ configs
./scripts/dev.sh config.yml db_config.yml      # custom configs
PORT=9090 ./scripts/dev.sh                     # custom port
```

### Module invocation (no install needed)

```bash
uv run python -m py_experimenter_db \
    --config config.yml \
    --db-config db_config.yml
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

The Chat section provides an LLM assistant (Claude) that is aware of your experiment schema, keyfields, result fields, and recent query history.

In addition to natural-language conversation, you can write and run Python scripts directly in the browser. Scripts have access to a `query(sql)` helper that returns a Pandas DataFrame:

```python
df = query("SELECT learning_rate, AVG(accuracy) as acc FROM my_experiments WHERE status='done' GROUP BY learning_rate")
print(df)
```

Matplotlib figures produced by scripts are captured and displayed inline. stdout and stderr are shown in collapsible panels.

Sessions and their history are stored persistently in the local workspace SQLite database.

---

## Local persistence

All workspace-local data (query history, saved queries, chat sessions, scripts, settings) is stored in a SQLite database inside the project directory:

```
.py_experimenter_dashboard/
└── query_history.sqlite
```

This file is created automatically on first run and persists across restarts.

A separate global registry tracks all projects that have ever been opened with the dashboard:

```
~/.py_experimenter_dashboard/
├── projects.db      # global project registry + cross-project Chat memory
```

---

## Project structure

```
py_experimenter_db/
├── config.py                  # YAML config parsers
├── cli.py                     # CLI entry point
├── __main__.py                # python -m py_experimenter_db support
├── db/
│   ├── connection.py          # async MySQL connection pool (aiomysql)
│   ├── schema.py              # live DB introspection + SchemaInfo
│   └── queries.py             # all SQL query functions
├── history/
│   └── store.py               # SQLite persistence (aiosqlite)
└── dashboard/
    ├── app.py                 # FastAPI application factory
    ├── state.py               # AppState dataclass
    ├── settings.py            # dashboard settings model
    ├── project_registry.py    # global project registry (cross-project)
    ├── code_runner.py         # sandboxed Python script execution
    ├── llm.py                 # Claude API client
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
| [CodeMirror 5](https://codemirror.net/5/) | SQL and YAML editors with syntax highlighting, folding, and autocomplete |
| [aiomysql](https://aiomysql.readthedocs.io/) | Async MySQL driver |
| [aiosqlite](https://aiosqlite.omnilib.dev/) | Async SQLite (local persistence) |

---

## Releasing a new version

- Create an API Token on [PyPI](https://pypi.org/).
- Add the token to your repository secrets as `PYPI_TOKEN` on the [Actions secrets page](https://github.com/mwever/py-experimenter-dashboard/settings/secrets/actions/new).
- Create a [new release](https://github.com/mwever/py-experimenter-dashboard/releases/new) on GitHub with a tag in the form `*.*.*`.

---

Repository scaffolded with [fpgmaas/cookiecutter-uv](https://github.com/fpgmaas/cookiecutter-uv).
