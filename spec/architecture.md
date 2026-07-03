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

[SQLite  (src/db, ./data/agent.db)]  ◄── datasets + analysis runs (audit trail)
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| **UI** (`frontend/`) | Chat thread, upload, live step trace, code panel, labelled stubs. Static export; talks to backend over REST + SSE. |
| **API** (`src/api`) | Upload/profile endpoint, ask (SSE stream) endpoint, run-history endpoints. `ok()`/`api_error()` envelope. |
| **Orchestration** (`src/graph`) | LangGraph agent: plan → generate_code → execute_locally → verify → answer, with fast-path and bounded retry/refine. |
| **Privacy choke point** (`src/analysis/privacy.py`) | The single function that builds every LLM prompt. Guarantees only schema + N samples leave. |
| **Local executor** (`src/analysis/executor.py`) | Runs generated pandas code against the full DataFrame in a restricted namespace with a timeout. |
| **Dataset store** (`src/analysis/store.py`) | Persists uploaded files on disk, loads them to DataFrames, computes schema + samples. |
| **LLM** (`src/llm`) | `LLMClient().call_model(prompt, system=...)` → Anthropic. Provider auto-detected from `.env`. |
| **Persistence** (`src/db`) | SQLite via SQLAlchemy 2.0. `DatasetRow`, `AnalysisRunRow` (audit trail). |

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

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Anthropic API | Claude writes plan / code / phrasing (schema+samples only) | Node catches error → sets `state["error"]` → `handle_error` → SSE `error` event; run persisted as `failed`. Retry/backoff in `src/llm`. |
| pandas / numpy | Local execution of generated code against full data | Execution error caught by executor → retry/refine loop (bounded) → best-guess-with-flag. |
| SQLite (SQLAlchemy 2.0) | Dataset metadata + analysis-run audit trail | On DB error the API returns 500 via `api_error`; the analysis result is still streamed if computed. |
| LangSmith (optional) | Tracing when `LANGCHAIN_TRACING_V2=true` in `.env` | Absent tracing is a no-op; never blocks a run. |
| Local filesystem (`./data/uploads`) | Raw uploaded files | Missing/unreadable file → dataset load error surfaced as a 400 on ask. |

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

**Avoid:** sending any DataFrame or raw rows into `src/llm` or `src/analysis/privacy.py` (breaks the invariant). No pandas `read_*` inside generated code (executor supplies `df`). No `eval`/`import` in the executor namespace. No second Python package — extend `src/` in place (bare imports, `pythonpath=["src"]`). No SQLite-substitute for the gate — gates run the real driver + real Anthropic key.

## Deployment Model

Local, long-running process on the user's machine. Build the frontend once (`cd frontend && pnpm build` → `frontend/out`), run migrations (`uv run alembic upgrade head`), then `uv run python -m src`. FastAPI serves both the API and the static UI at `http://localhost:8001/app/`. No container, no cloud, no auth — single trusted user.
