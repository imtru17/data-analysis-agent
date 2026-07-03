# Architecture

---

## System Overview

A single-user, local-first web application. A Next.js chat UI (static export, served at `/app`) talks to a FastAPI backend (port 8001) on the same machine. The backend orchestrates a LangGraph agent that answers data questions by writing code with Claude and **executing that code locally** against the user's full dataset. The architectural centre of gravity is the **privacy boundary**: the only data that ever crosses to the Anthropic API is a dataset's schema (column names + dtypes) plus a bounded number of sample rows. Everything else — the full file, all computed results — stays in-process on the user's machine. SQLite persists an audit trail of every run.

## Component Map

```
[Next.js chat UI  (frontend/, served at /app)]
        │  REST + SSE (fetch)
        ▼
[FastAPI app  (src/api)]  ──► [Dataset store  (src/analysis/store.py, ./data/uploads/)]
        │                              ▲
        ▼                              │ full file (local only)
[Analysis runner  (src/graph/runner.py)]
        │
        ▼
[LangGraph agent  (src/graph/agent.py)]
   plan → generate_code → execute_locally → verify → answer
        │                    │
        │  schema+samples     │  full DataFrame
        ▼  ONLY               ▼  local, restricted namespace
[LLM choke point  (src/analysis/privacy.py)]     [Local executor  (src/analysis/executor.py)]
        │                                                (no network, timeout, restricted builtins)
        ▼
[Anthropic API  (src/llm)]  ◄── schema + N sample rows ONLY, never raw data

[SQLite  (src/db, ./data/agent.db)]  ◄── datasets + analysis runs (audit trail) + sessions/messages/connections/annotations (P3)
```

Phase-3 adds a **Source abstraction** in front of execution: a file source runs pandas locally (as above), while a **DB source** (`src/analysis/db_source.py`) runs generated **read-only SQL pushed down** to the user's Postgres/MySQL/SQLite over a SQLAlchemy engine — only schema + a `LIMIT` sample + a bounded result ever cross to Claude, and the connection string stays in SQLite (masked everywhere else):

```
[Analysis runner] ──► [select_sources] ──► ... ──► [execute_locally (source-aware)]
                                                       │ file  ─► pandas-local (full df in restricted namespace)
                                                       │ DB    ─► SQL pushdown ─► [User Postgres/MySQL/SQLite]
                                                       └ multi ─► per-source bounded intermediates ─► local combine
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| **UI** (`frontend/`) | Chat thread, upload, live step trace, code panel; Phase 2 profile/charts/cost/export; Phase 3 connect-DB, multi-source picker, session/history browser, annotation editor. Static export; talks to backend over REST + SSE. |
| **API** (`src/api`) | Upload/profile, ask (SSE stream), run-history; Phase 2 cost/exports; Phase 3 sources/connections, sessions, annotations. `ok()`/`api_error()` envelope. |
| **Orchestration** (`src/graph`) | LangGraph agent: (Phase 3) select_sources → plan → generate_code → execute_locally → verify → answer → chart_spec, with fast-path and bounded retry/refine. |
| **Privacy choke point** (`src/analysis/privacy.py`) | The single function that builds every LLM prompt. Guarantees only schema + N samples (+ bounded result summary + annotations + bounded conversation) leave — for both file and DB sources. |
| **Local executor** (`src/analysis/executor.py`) | Runs generated pandas code against the full DataFrame in a restricted namespace with a timeout. |
| **Source abstraction** (`src/analysis/sources/`, Phase 3) | A `Source` is a **file source** (pandas-local) or a **DB source** (SQL pushed down to the DB). Both expose `schema()`, bounded `sample()`, and `execute(code_or_sql)` → bounded result summary. |
| **Dataset store** (`src/analysis/store.py`) | Persists uploaded files on disk, loads them to DataFrames (CSV in P1; Excel/JSON/Parquet/PDF/log in P3), computes schema + samples. |
| **DB source** (`src/analysis/db_source.py`, Phase 3) | SQLAlchemy engine per connection; introspects schema, draws a `LIMIT N` sample, executes read-only pushdown SQL and returns a bounded intermediate. Holds the connection string in-process only. |
| **LLM** (`src/llm`) | `LLMClient().call_with_usage(prompt, system=...)` → Anthropic. Provider auto-detected from `.env`. |
| **Persistence** (`src/db`) | SQLite via SQLAlchemy 2.0. `DatasetRow`, `AnalysisRunRow`; Phase 3 `SessionRow`, `SessionMessageRow`, `ConnectionRow`, `ColumnAnnotationRow`. |

## Data Flow

1. **Trigger:** user uploads a CSV in the chat UI → `POST /datasets` (multipart).
2. Backend saves the raw file to the local dataset store (`./data/uploads/<dataset_id>.csv`), loads it with pandas, computes **schema (columns+dtypes), row count, and N sample rows**, writes a `DatasetRow`, and returns the profile (schema + samples + row count) to the UI.
3. User types a question → `POST /analyses` with `{dataset_id, question}`; response is `text/event-stream` (SSE).
4. The runner starts the LangGraph agent and streams a **step event per node** as the graph advances: `plan`, `generate_code`, `execute_locally`, `verify`, `answer`.
5. **plan** (skipped on the fast path) and **generate_code** call Claude via the privacy choke point — sending **only schema + samples** — and Claude returns pandas code.
6. **execute_locally** runs that code in the restricted namespace against the **full** DataFrame; results (numbers, a small result table) stay local.
7. **verify** sanity-checks results (row counts / nulls / totals); on failure or execution error it loops back to `generate_code` (bounded retries), then falls through to a best-guess-with-flag.
8. **answer** calls Claude with **schema + samples + the computed result summary** (still no raw rows) to phrase a plain-language answer.
9. **Output:** the final SSE `done` event carries the answer + generated code + step trace; the `finalize` step persists an `AnalysisRunRow` (question, code, result summary, timestamp, tokens/cost fields). The UI renders the answer and the collapsible code panel.

## Privacy Architecture (the invariant boundary — CRITICAL)

**Invariant:** for any dataset, the bytes that reach the Anthropic API are **only** (a) the schema — an ordered list of `{column_name, dtype}` — and (b) at most `AGENT_SAMPLE_ROWS` (default 5) sample rows rendered as text. The full dataset, and all computed results beyond a small summary, never appear in any LLM request.

**How it is enforced:**

- **Single choke point.** `src/analysis/privacy.py` exposes `build_llm_context(dataset_meta) -> LlmContext` and `render_context(ctx) -> str`. Every node that calls the LLM builds its prompt from this rendered context and **must not** touch the DataFrame directly. `LlmContext` holds only `columns`, `dtypes`, `sample_rows` (already truncated), `row_count`, and — for the answer node — a `result_summary` (scalars / a tiny aggregated table produced by *local* code, capped in size). It has no reference to the full DataFrame.
- **Sample bounding.** Samples are drawn once at profile time (`store.profile()`), truncated to `AGENT_SAMPLE_ROWS`, with per-cell string length capped (default 200 chars) so wide/long cells can't smuggle bulk data. Sampling is deterministic (head, or a seeded sample) for reproducibility.
- **Result summary bounding.** After local execution, only a capped summary reaches the answer node: scalars pass through; a result table is truncated to at most `AGENT_RESULT_ROWS` (default 20) rows and its cells length-capped. If a result exceeds the cap, the summary carries shape + head only, and the answer says so.
- **The full file only ever flows to the local executor**, never to `privacy.py` or `src/llm`. The type system helps: LLM-calling nodes receive `LlmContext`, not `DataFrame`.
- **Test-enforced.** `tests/unit/test_privacy.py` monkeypatches the Anthropic transport to capture the exact outbound request body and asserts: (1) every prompt string is a superset of the schema, (2) it contains at most N sample rows, and (3) it contains **none** of a set of sentinel cell values planted in non-sampled rows of a fixture dataset. This test is part of the Phase-1 gate.

**Uploaded-file storage.** Raw files are written under `./data/uploads/<dataset_id>.<ext>` (git-ignored). `DatasetRow` stores metadata + the relative path, never the contents. Files persist across restarts so a dataset can be re-queried; deletion is manual (Phase 1) or via a session/dataset delete (Phase 3).

**Sandboxing the generated code.** `executor.py` runs generated pandas in a **restricted namespace**:
- Executed via `exec(compiled, restricted_globals, locals)` where `restricted_globals` exposes only `pd` (pandas), `np` (numpy), the input `df`, and a curated safe subset of builtins (`len`, `sum`, `min`, `max`, `sorted`, `range`, `round`, `abs`, `list`, `dict`, `set`, `tuple`, `str`, `int`, `float`, `bool`, `enumerate`, `zip`, etc.). No `__import__`, `open`, `eval`, `exec`, `compile`, `input`, `globals`, `getattr`-escape, or dunder-traversal helpers.
- A **static pre-check** rejects code containing `import`, `__`, `open(`, `eval`, `exec`, `subprocess`, `os.`, `sys.`, `socket`, `requests`, `urllib`, `Path`, `write` before execution (defense-in-depth alongside the namespace restriction).
- **Wall-clock timeout** (`AGENT_EXEC_TIMEOUT`, default 30s) enforced by running the exec in a worker thread and abandoning it on timeout (best-effort on CPython; documented limitation — a truly runaway thread can't be force-killed, so the timeout surfaces an error to the user and the request returns).
- **No network / no filesystem escape by construction** (no import, no `open`). This is defense-in-depth for a **trusted single user running their own machine** — it is explicitly NOT a hostile-multi-tenant sandbox, and that limit is documented here and in `spec/agent.md`.
- The generated code must assign its answer to a conventional variable (`result`); the executor returns `result` plus captured stdout for the trace.

## Phase 3 — Sources, Sessions, Memory, Multi-source (the invariant, extended)

Phase 3 breaks past a single in-memory CSV without weakening the privacy boundary. The invariant is unchanged: **only schema + bounded samples + a bounded result summary (+ user-authored annotations + prior-turn prose) ever reach Claude** — for every source kind.

### Source abstraction (`src/analysis/sources/`)

A **Source** is one of:

- **File source** — a dataset backed by a file on disk (CSV/Excel/JSON/Parquet/PDF/log). Generated **pandas** runs locally against the full DataFrame in the restricted executor (exactly the Phase-1 path).
- **DB source** (`src/analysis/db_source.py`) — a live SQL database reached over a SQLAlchemy engine. Generated **read-only SQL** is **pushed down** to the DB; the full table never leaves the DB.

Both expose the same surface, so the graph is source-agnostic above execution:

| Method | File source | DB source |
|--------|-------------|-----------|
| `schema()` | pandas dtypes | SQLAlchemy `inspect(engine)` — table/column names + types |
| `sample(n)` | `df.head(n)`, cell-capped | `SELECT * FROM <t> LIMIT n`, cell-capped |
| `execute(code_or_sql)` | run pandas locally, return **bounded** summary | run read-only SQL in the DB, fetch a **bounded** intermediate, return **bounded** summary |

### DB-pushdown privacy boundary (CRITICAL)

For a DB source, the bytes that reach Claude are **only** (a) the introspected schema, (b) a `LIMIT AGENT_SAMPLE_ROWS` sample, and (c) the bounded result summary of the executed query. The generated SQL executes **inside the database engine** — so a billion-row table is filtered/aggregated by the DB and only a small result set is fetched back into the process. DB-sized tables never load into memory and never appear in any prompt. Generated SQL is validated **read-only**: only `SELECT`/`WITH` are allowed; `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT` and multiple statements are rejected before execution (defense-in-depth + honours "never mutate source data"). A safety `LIMIT` (`AGENT_SQL_MAX_ROWS`, default 100000) wraps any un-aggregated fetch so a stray `SELECT *` cannot pull the whole table into memory.

### Secret hygiene for connection strings (see `harness/rules/secret-hygiene.md`)

A DB connection string may contain credentials. It is therefore:

- **Stored only in the local, git-ignored SQLite DB** (`ConnectionRow.dsn`), never in source, never in `.env`-tracked files. Modelled as a pydantic `SecretStr` in-memory; `.get_secret_value()` is called only at the SQLAlchemy engine boundary.
- **Never sent to the LLM** — the privacy choke point only ever receives schema/samples/summaries; a connection string is not part of any `LlmContext`.
- **Never logged** — structlog logs `connection_id` + `dialect` + `host` only, never the DSN; exception messages never embed it.
- **Never returned in full by the API** — `POST /connections` and `GET /connections` return a **masked** DSN (`postgresql://user:***@host:5432/db`). The raw value is write-only from the client's perspective.

### Non-CSV file loading (`src/analysis/sources/loaders.py`)

The store gains per-format loaders, each producing a DataFrame profiled to schema + bounded sample (same invariant):

| Format | `source_kind` | Loader | Notes |
|--------|---------------|--------|-------|
| Excel | `excel` | pandas + **openpyxl** | first sheet by default; sheet name optional |
| JSON | `json` | `pandas.read_json` / `json_normalize` | nested JSON flattened to columns |
| Parquet | `parquet` | pandas + **pyarrow** (already a dep) | columnar, dtypes preserved |
| PDF | `pdf` | **pdfplumber** table extraction | first/best table → DataFrame |
| log / text | `log` | line reader → structured or single `line` column | best-effort field parse; else one text column |

**Graceful degradation:** when a format yields no clean tabular data (typically a PDF with no detectable table, or an unparseable log), the loader raises a friendly `BAD_REQUEST` ("Couldn't find a table in that PDF — try CSV/Excel/Parquet") rather than crashing; the upload is rejected with the reason, and no orphan file is left on disk. `DatasetRow.source_kind` records the format; on-disk files keep their original extension (`<dataset_id>.<ext>`).

### Sessions, conversation memory, annotations

- **Sessions** (`SessionRow`) own many datasets/connections, runs, messages, and annotations. On upload/connect the row is linked to the active session (`DatasetRow.session_id`). Reopening the app lists sessions; opening one restores its datasets, connections, conversation thread, and annotations — including across days (persisted in SQLite).
- **Conversation memory** (`SessionMessageRow`) — each turn's question + the agent's answer prose is appended in `finalize`. The runner loads the last `AGENT_MEMORY_TURNS` (default 8) into `conversation` and hands them to the LLM nodes via the choke point. This is prose the agent already produced from bounded summaries — **never raw rows**, never a DB table, never a DSN.
- **Annotations** (`ColumnAnnotationRow`) — user notes about a column's business meaning. They flow into `privacy.render_context` as short, user-authored text keyed to the selected source(s), improving code generation without exposing data.

### Multi-source auto-pick / join / compare

`POST /analyses` accepts one or several `source_ids` (files and/or DB connections). The `select_sources` node auto-picks the relevant source, or, when the question spans sources, selects several and emits a **decompose-then-combine** plan. Each source is reduced **on its own turf** — pandas-local for a file, SQL-pushdown for a DB — to a **bounded** intermediate; a final local pandas `combine_code` snippet joins/compares those bounded intermediates and assigns `result`, which is then bounded to `AGENT_RESULT_ROWS` like any other summary. Full tables stay home (the DB filters/aggregates in place; a file is reduced locally); only small, already-reduced intermediates ever meet in memory, so the invariant and the memory bound both hold. A true row-level join of two enormous sources is out of scope — the pattern is analyst-style compare/aggregate-then-join.

> **Assumed:** cross-source joins operate on per-source **aggregated/reduced** intermediates (each bounded), not a full row-level cross product of two large sources. This matches the primary journey ("compare revenue in the CSV to targets in the DB") and preserves the memory bound. Flagged for confirmation.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Anthropic API | Claude writes plan / code / phrasing (schema+samples only) | Node catches error → sets `state["error"]` → `handle_error` → SSE `error` event; run persisted as `failed`. Retry/backoff in `src/llm`. |
| pandas / numpy | Local execution of generated code against full data | Execution error caught by executor → retry/refine loop (bounded) → best-guess-with-flag. |
| SQLite (SQLAlchemy 2.0) | App metadata + audit trail + sessions + connections + annotations | On DB error the API returns 500 via `api_error`; the analysis result is still streamed if computed. |
| **User DB sources** (Postgres/MySQL/SQLite via SQLAlchemy, Phase 3) | Schema introspection + `LIMIT` sample + read-only pushdown SQL | Connect/query error → caught → `execution_result.error` → retry/refine; connect-fatal → `handle_error`. DSN masked in all responses/logs. |
| **openpyxl / pyarrow / pdfplumber** (Phase 3) | Load Excel / Parquet / PDF sources to DataFrames | Unreadable/no-table → friendly `BAD_REQUEST` at upload; no crash. |
| LangSmith (optional) | Tracing when `LANGCHAIN_TRACING_V2=true` in `.env` | Absent tracing is a no-op; never blocks a run. |
| Local filesystem (`./data/uploads`) | Raw uploaded files (CSV/Excel/JSON/Parquet/PDF/log) | Missing/unreadable file → dataset load error surfaced as a 400 on ask. |

## Stack

> Concrete choices for this project. Generic every-project rules (model-naming, DB driver, dev port, real-key tests) live in `harness/patterns/tech-stack.md`.

- **Language:** Python 3.11+ (backend), TypeScript (frontend). *(Skeleton pins `requires-python = ">=3.11"`.)*
- **Agent framework:** LangGraph (graph pattern — multi-step with conditional fast-path and retry/refine edges).
- **LLM provider + model:** Anthropic Claude, default `claude-sonnet-4-6`, env-configurable via `AGENT_LLM_MODEL`. A cheaper model may be selected per-node in Phase 2 for trivial/fast-path asks.
- **Backend:** FastAPI on port 8001 (`uv run python -m src` → uvicorn `api:app`).
- **Database + ORM:** SQLite (`sqlite:///./data/agent.db`) + SQLAlchemy 2.0; alembic migrations at repo root.
- **Frontend:** Next.js 15 static export (`output: 'export'`, `basePath: '/app'`) + React 19 + Tailwind 4, served by FastAPI from `frontend/out`.
- **Dependency management:** uv + `pyproject.toml` (Python); pnpm (frontend).

| Key library | Version | Purpose |
|-------------|---------|---------|
| langgraph | >=0.1 | Agent graph + step streaming |
| anthropic | >=0.28 | Claude client (schema+samples only) |
| pandas | >=2.2 (add) | Load CSV + execute generated code locally |
| numpy | >=1.26 (add, via pandas) | Numeric ops in executor namespace |
| fastapi / uvicorn | >=0.115 / >=0.30 | REST + SSE server |
| sqlalchemy / alembic | >=2.0 / >=1.13 | Persistence + migrations |
| structlog | >=24.1 | Structured request/response logging (day one) |
| @playwright/test | latest (frontend dev) | E2E smoke test of the core path |
| openpyxl | >=3.1 (add, Phase 3) | Excel (`.xlsx`) source loading |
| pdfplumber | >=0.11 (add, Phase 3) | PDF table extraction (graceful when no table) |
| psycopg2-binary | >=2.9 (add, **optional extra** `db`, Phase 3) | Postgres driver for DB sources |
| pymysql | >=1.1 (add, **optional extra** `db`, Phase 3) | MySQL driver for DB sources |
| duckdb | >=1.0 (add, Phase 4) | LOCAL, in-process SQL over the dataset's pandas DataFrame (the workbench SQL query box) — no network, no data egress |
| plotly.js-dist-min | latest (frontend, add, Phase 5) | Interactive rotatable 3D chart, **bundled locally** (no external CDN); existing 2D charts stay on Vega-Lite |
| boto3 | latest (add, **optional extra** `cloud`, Phase 5) | AWS S3 "create table" connector — **stubbed & gated out of the build**; live call only when credentials are supplied |
| snowflake-connector-python | latest (add, **optional extra** `cloud`, Phase 5) | Snowflake "create table" connector — **stubbed & gated out of the build** |

> Phase-3 note: **pyarrow** (Parquet) is already a dependency. **SQLite** DB sources need no extra driver (stdlib). Postgres/MySQL drivers ship as an optional `db` extra (`uv sync --extra db`) so the base install and the Phase-3 gate stay driver-light — the gate exercises the DB-source path against a **local seeded SQLite DB**, needing no external credentials.

> Phase-4 note: **duckdb** runs entirely in-process against the DataFrame already loaded from the local file — the **profile tiles and the SQL query box are LOCAL-only and preserve the privacy invariant by construction** (nothing leaves the machine, no prompt is built, no LLM call). New setting `AGENT_WORKBENCH_DISPLAY_ROWS` (default 500) caps the displayed result table; downloads re-run the SQL for the full result. FK detection scans other loaded datasets (same-session, else recent `AGENT_WORKBENCH_FK_SCAN`, default 25).

> Phase-5 note: **plotly.js-dist-min** is bundled into the static frontend export — no external CDN, keeping the local-first, self-contained deployment. Cloud connectors (**boto3**, **snowflake-connector-python**) ship as an optional `cloud` extra (`uv sync --extra cloud`) and are **stubbed** so the Phase-5 build/gate need **no AWS/Snowflake credentials**; the local/Postgres create-table path is real. Any cloud action is opt-in and shows an explicit data-egress warning.

**Avoid:** sending any DataFrame or raw rows into `src/llm` or `src/analysis/privacy.py` (breaks the invariant). Sending a full DB table into memory or into a prompt — DB work is pushed down as read-only SQL, only bounded results return. Putting a connection string (DSN) into any `LlmContext`, log line, exception message, or API response (mask it; store only in the git-ignored SQLite DB via `SecretStr`). Generated DB code that is not a single read-only `SELECT`/`WITH`. No pandas `read_*` inside generated code (executor supplies `df`). No `eval`/`import` in the executor namespace. No second Python package — extend `src/` in place (bare imports, `pythonpath=["src"]`). No SQLite-substitute for the *audit* DB gate — gates run the real driver + real Anthropic key; the DB-*source* gate uses a real local SQLite database as a genuine pushed-down source.

## Deployment Model

Local, long-running process on the user's machine. Build the frontend once (`cd frontend && pnpm build` → `frontend/out`), run migrations (`uv run alembic upgrade head`), then `uv run python -m src`. FastAPI serves both the API and the static UI at `http://localhost:8001/app/`. No container, no cloud, no auth — single trusted user.
