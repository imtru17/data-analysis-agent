# Roadmap

---

## What This Agent Does

A local-first, chat-style data analysis agent for a single technical user. The user uploads a dataset (CSV in Phase 1; more formats and live DB connections later), asks questions in plain English, and gets back correct plain-language answers with the key numbers — plus the exact code the agent ran and a live trace of what it did. The **defining constraint** is privacy: the LLM (Claude) only ever sees the dataset's **schema (column names + dtypes)** and a **small number of sample rows**. From that, Claude writes pandas/SQL code, and that code executes **locally, against the full dataset**. Raw data is never sent to the LLM API. This invariant governs the whole architecture and is real and correct from Phase 1.

## Who Uses It

A single technical user (data analyst / engineer / founder) running the tool on their own machine for daily, personal analysis. They are comfortable with data concepts, want fast answers without writing boilerplate pandas/SQL, and care about keeping their raw data private and their LLM spend visible. No multi-tenant, no auth, no team collaboration.

## Core Problem Being Solved

Ad-hoc data analysis today means either (a) hand-writing pandas/SQL for every question, which is slow, or (b) pasting raw data into a hosted LLM tool, which leaks private data and can be expensive. This agent removes both problems: it writes and runs the code for you, and it does so while keeping raw rows on your machine — only schema and a handful of samples ever leave.

## Success Criteria

- [ ] A user can upload a CSV, ask a natural-language question, and receive a correct plain-language answer with the key numbers, first try, with no rough edges on that path.
- [ ] For every question, only schema (column names + dtypes) + a bounded number of sample rows are sent to the Anthropic API — verifiable by inspecting the exact request payload; the full dataset is never in any LLM request.
- [ ] The generated pandas code is shown to the user in a collapsible panel and, when re-run locally against the same file, reproduces the reported numbers.
- [ ] The user sees live step-by-step progress (plan → generate code → execute → verify → answer) stream into the UI while the agent works, not just a spinner.
- [ ] Every completed analysis (question, generated code, result summary, timestamp) is persisted to the local DB and retrievable, forming an audit trail.

## What This Agent Does NOT Do (Out of Scope)

- Never sends raw data rows (beyond the bounded schema-sample) to any LLM or third-party API.
- No multi-user support, authentication, accounts, or team sharing — single local user only.
- No cloud deployment, no hosted service — runs on the user's machine.
- No autonomous data mutation of source files (it reads and derives; it never overwrites the user's original upload).
- No arbitrary internet browsing or external API calls from generated code — executed code runs in a restricted, network-denied namespace.
- Phase 1 only: no charts, no exports/report, no DB connections, no multi-source join/compare, no auto-profiling, no cost/token display, no cross-day session persistence, no non-CSV formats — these are visible, clearly-labelled stubs in Phase 1 and are delivered in later phases.

## Key Constraints

- **Privacy invariant (hard):** only schema + N sample rows (default N=5, configurable) reach the LLM. Enforced at a single choke point and covered by a test that inspects the outbound payload.
- **Local execution:** generated code runs in-process against the full file in a restricted namespace (no `import` of network/OS-escape modules, no filesystem writes outside the dataset store, wall-clock timeout). Sandbox is best-effort defense-in-depth for a trusted single user, not a hostile-multi-tenant sandbox — documented as such.
- **Data scale:** Phase 1 targets CSVs up to ~500 MB read with pandas; large/DB-sized data uses SQL pushdown + sampling in Phase 3. Phase 1 loads the whole CSV into memory.
- **Cost/latency:** default model `claude-sonnet-4-6`; a fast single-pass path for trivial asks (skip planning). Model is env-configurable (`AGENT_LLM_MODEL`).
- **Observability from day one:** structured request/response logging (prompt, output, latency, token counts, model, run_id) to stdout in Phase 1; LangSmith tracing enabled when `LANGCHAIN_TRACING_V2` is set in `.env`.
- **Platform:** runs on the existing skeleton — FastAPI on port 8001, `uv run python -m src`, SQLite, Next.js static export served at `/app`.

## Phases of Development

> **Phase 1 is the smallest first-time-right user-testable win.** Backend is minimal but REAL on the one core path (no fake data). Frontend is visually complete: real UI for the upload→ask→answer path PLUS clearly-labelled NON-FUNCTIONAL stubs for everything coming later.

### Phase 1 — CSV upload → ask → local-execution answer (the core privacy path)

- **Goal:** The user uploads a CSV in the chat UI, types a natural-language question, and receives a correct plain-language answer with key numbers — where only schema + sample rows are sent to Claude, Claude's pandas code executes locally against the full file, the answer shows the generated code in a collapsible panel and streams live step updates while working, and the run (question, code, result, timestamp) is written to the DB.
- **Independent slices (parallel build units):**
  - `backend-analysis` (backend, `src/`) — replaces the `transform_text` capability with the full analysis pipeline: upload+profile the CSV to schema/samples, the LangGraph plan→generate_code→execute_locally→verify→answer graph, the restricted local pandas executor, the privacy choke point, SSE streaming endpoint, upload/ask/history REST endpoints, DB models for datasets + analysis runs, prompts, and pytest suite. Deps: none. **Rationale for one backend slice:** the privacy invariant spans executor + node + choke point + API and must be correct as a single cohesive unit; splitting it would create serializing dependencies rather than parallelism.
  - `frontend-chat` (frontend, `frontend/`) — the chat UI: upload control, message thread, live step trace, collapsible code panel, plain-language answer, and every labelled "coming soon" stub (charts, exports, DB-connect, multi-source, profiling/follow-ups, cost/token+daily total, sessions/history browser, non-CSV). Plus the Playwright E2E smoke test. Deps: none — consumes the API contract in `spec/api.md`, mocked in E2E where needed and run against the real server for the smoke path.
- **Key surfaces / files:**
  - backend: `src/analysis/` (new: `store.py`, `profile.py`, `executor.py`, `privacy.py`), `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/graph/runner.py`, `src/prompts/plan.md`, `src/prompts/generate_code.md`, `src/prompts/answer.md`, `src/api/analyses.py`, `src/api/datasets.py`, `src/api/__init__.py` (register routers), `src/db/models.py`, `src/domain/analysis.py`, `alembic/versions/*`, `tests/unit/**`, `tests/integration/test_analysis_pipeline.py`.
  - frontend: `frontend/src/app/page.tsx`, `frontend/src/app/components/*`, `frontend/src/lib/api.ts`, `frontend/tests/e2e/analysis.spec.ts`, `frontend/playwright.config.ts`, `frontend/package.json` (add `@playwright/test`).
- **Gate command:** `uv run alembic upgrade head && uv run pytest tests/ -q` (backend, real Anthropic key from `.env`) **and** `cd frontend && pnpm build && pnpm exec playwright test` (frontend E2E against the built app + running server). The pytest suite includes the privacy-payload assertion and a full upload→ask→answer integration test against the real API.
- **How the user tests it (handoff seed):**
  1. Ensure `.env` has `AGENT_ANTHROPIC_API_KEY`. Run `uv run alembic upgrade head`, then `cd frontend && pnpm build`, then `uv run python -m src`.
  2. Open `http://localhost:8001/app/`.
  3. Upload a CSV (e.g. a sales file). Expect a confirmation message showing detected columns + dtypes and row count (the profile).
  4. Type e.g. "What's the total revenue by region?" and send. Expect: live step chips appear in order (Planning → Writing code → Running locally → Verifying → Answering), then a plain-language answer with the numbers.
  5. Click "Show code" — expect the exact pandas snippet the agent ran.
  6. **Real vs stub:** the upload box, the message thread, the live steps, the answer, and the code panel are REAL. Everything in the right-hand "Coming soon" rail and the greyed toolbar buttons (Charts, Export, Connect DB, Add source, Profile, Cost/Today's spend, History, non-CSV upload) are clearly-labelled NON-FUNCTIONAL stubs — they show a "Coming soon" tooltip/badge and do nothing when clicked.

### Phase 2 — Insight surface: Profiling + Charts + Cost/Token + Exports

- **Goal:** Turn the passive answer into an insight surface. On upload the agent auto-profiles the dataset and suggests 2–3 follow-up questions; answers can render an interactive, downloadable chart (auto-chosen or user-requested); every answer shows its token count + cost and a running daily total; and the user can export the cleaned/derived dataset (CSV/Parquet), the code the agent ran, and a shareable prose+tables+charts report. Wires the Phase-1 stubs for Profile, Follow-ups, Charts, Cost/Token, and Exports into real functionality.
- **Independent slices (parallel build units):**
  - `backend-insight` (backend, `src/`) — auto-profile node + follow-up suggestion, a chart-spec generator node (agent emits a Vega-Lite/JSON chart spec from schema+result, never raw data to a chart service), token/cost accounting from the Anthropic response usage + a daily-total aggregate, export builders (cleaned dataset, code, report). New endpoints; extend DB with cost fields (already present) + export records. Deps: none (extends Phase-1 graph).
  - `frontend-insight` (frontend, `frontend/`) — profile card + clickable follow-up chips, chart renderer (zoom + PNG/SVG download), cost/token badge per answer + today's-total header, export menu. Deps: none. E2E extended.
- **Key surfaces / files:** backend `src/graph/nodes.py` (profile, chart_spec nodes), `src/analysis/cost.py`, `src/analysis/export.py`, `src/api/analyses.py`, `src/api/exports.py`, `src/prompts/profile.md`, `src/prompts/chart.md`; frontend `frontend/src/app/components/{ProfileCard,Chart,CostBadge,ExportMenu}.tsx`, `frontend/tests/e2e/insight.spec.ts`.
- **Gate command:** `uv run alembic upgrade head && uv run pytest tests/ -q` (includes a chart-spec test, a cost-accounting test asserting tokens/cost recorded from the real Anthropic usage, and an export round-trip test) **and** `cd frontend && pnpm build && pnpm exec playwright test`.
- **How the user tests it (handoff seed):** upload a CSV → see the auto-profile card + 3 follow-up chips; ask a "show me a chart of…" question → see a zoomable chart, download it as PNG; observe the token/cost badge on the answer and the "Today: $x" header increment; open Export → download cleaned CSV, the code, and the report. Stubs remaining: DB-connect, multi-source, sessions/history browser, non-CSV.

### Phase 3 — Beyond one CSV: DB connections + Multi-source join/compare + Sessions/Annotations + non-CSV formats

- **Goal:** Break past a single in-memory CSV. Connect to a live SQL database (Postgres/MySQL/SQLite via SQLAlchemy) with SQL pushdown/sampling for DB-sized tables; load non-CSV files (Excel, JSON, Parquet, PDF, log/text); keep persistent cross-day sessions that remember conversation history, loaded + derived datasets, and user column/business annotations; and let the agent auto-pick, join, and compare across multiple loaded sources. Wires the remaining Phase-1 stubs: Connect DB, Add source/multi-source, Sessions/History browser, non-CSV upload, Annotations.
- **Independent slices (parallel build units):**
  - `backend-sources` (backend, `src/`) — pluggable source loaders (Excel/JSON/Parquet/PDF/log), SQLAlchemy DB-connection source with schema introspection + SQL pushdown + sampling, multi-source registry, join/compare planning in the graph, annotation store. Deps: none (extends Phase-1/2 graph + store).
  - `backend-sessions` (backend, `src/`) — persistent session model, conversation-history memory across days, session/dataset/annotation retrieval endpoints. Deps: **serializes after `backend-sources`** only for the shared `src/db/models.py` + `src/analysis/store.py` schema (declare the shared migration as owned by `backend-sources`; `backend-sessions` adds its own migration on top). Otherwise independent.
  - `frontend-sources` (frontend, `frontend/`) — DB-connect dialog, non-CSV upload, multi-source panel + source picker, session/history browser, annotation editor. Deps: none. E2E extended.
- **Key surfaces / files:** backend `src/analysis/sources/*.py`, `src/analysis/db_source.py`, `src/analysis/annotations.py`, `src/graph/nodes.py` (source-pick/join node), `src/api/{sources,sessions,annotations}.py`, `src/db/models.py`, new alembic migrations; frontend `frontend/src/app/components/{ConnectDb,SourcePanel,SessionBrowser,AnnotationEditor}.tsx`, `frontend/tests/e2e/sources.spec.ts`.
- **Gate command:** `uv run alembic upgrade head && uv run pytest tests/ -q` (includes a DB-source pushdown test against a seeded SQLite DB proving sampling + only-schema-to-LLM, a non-CSV load test, a multi-source join test, and a cross-day session-restore test) **and** `cd frontend && pnpm build && pnpm exec playwright test`.
- **How the user tests it (handoff seed):** connect a local SQLite/Postgres DB or upload a Parquet/Excel file; ask a question that spans two sources ("compare revenue in the CSV to targets in the DB") → agent picks/joins sources and answers; close and reopen the app next day → prior session, datasets, and annotations are restored; add a business annotation to a column and see the agent use it. No stubs remain from the Phase-1 vision.
