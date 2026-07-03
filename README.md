# Local-first Data Analysis Agent

A single-user, local-first data analysis agent. Upload a CSV, ask a question in plain English, and get a correct plain-language answer with the key numbers — plus the exact pandas code the agent ran and a live step-by-step trace.

**The privacy invariant (the whole point):** only the dataset's **schema (column names + dtypes) and a bounded number of sample rows** ever reach the Anthropic API. Claude writes pandas code from that alone; the code executes **locally against your full dataset**. Raw data never leaves your machine. This is enforced at a single choke point (`src/analysis/privacy.py`) and covered by a payload-capture test.

Built on the spec-driven harness below (FastAPI + LangGraph + SQLite + Anthropic).

---

## The Spirit

Six convictions the whole repo is built around:

1. **Spec is the source of truth.** The spec is written before the code, always. When spec and code disagree, the spec wins and the code is fixed (`/zero-shot-sync`). Every AI session reads the same requirements instead of re-deriving them.
2. **Built for two audiences at once.** A non-coder drives it with a single sentence; a senior engineer inherits a clean FastAPI + LangGraph stack they can read, review, and own. Neither audience is an afterthought.
3. **Lean harness, not a framework.** `harness/` is engineering *mindfulness* — rules and patterns that keep every session consistent — deliberately Claude-Code-only and kept small. The product runtime stays provider-agnostic; the harness does not.
4. **Smallest first-time-right win, phase by phase.** Each phase ships the smallest increment a human can actually test, and it must work the *first* time they test it — real on the tested path, with clearly-labelled stubs for everything still to come. No rough edges on the path you're handed.
5. **A human gates every phase.** The build is autonomous *within* a phase and stops at each boundary for you to test the increment. You stay in control of what "done" means.
6. **Real LLM/API or it doesn't count.** Gates, tests, and evals run against the real model with keys from `.env`. A stubbed pass is not a pass.

---

## What This Is

A starting point for building AI agents spec-first. The repo ships with:

- A working **baseline agent** in `src/` (FastAPI + LangGraph + SQLite, provider-agnostic LLM — Anthropic or Gemini, `transform_text` as the capability slot) — tests pass out of the box
- A **spec template** in `spec/` covering roadmap, architecture, capabilities, data model, API, UI, and agent graph
- Three **zero-shot skills** (`/zero-shot-build`, `/zero-shot-fix`, `/zero-shot-sync`)
- A four-agent **team** — agent-builder orchestrates (plans, fans out, owns git/PR); spec-writer is the single design authority; code-generator implements one slice per instance (parallelised); qa-auditor reviews and gates
- Engineering rules and patterns in `harness/` so every Claude Code session is consistent
- **Human testing gate between phases** — autonomous within a phase, you test each increment before the next starts

---

## How to Use This

### Step 1 — Clone

```bash
git clone https://github.com/smallTechOrg/zero-shot-sdd-harness.git my-agent
cd my-agent
```

### Step 2 — Open in Claude Code

```bash
claude
```

### Step 3 — Build

```
/zero-shot-build An agent that monitors my Shopify store for low-inventory products and drafts restock emails to suppliers
```

One intake round (scope, stack, API keys → fill `.env`), then the agent builds phase by phase and stops at each boundary for you to test.

---

## What Happens (Intake → Phase by Phase)

```
Your idea
    ↓
INTAKE — scope, stack, LLM provider, constraints; fill .env with the required API key
    ↓
[spec-writer]  → Full spec: architecture + agent-graph + phased plan (self-reviewed)
    ↓
[agent-builder] → Feature branch + PR, scaffold
    ↓
per phase — all slices concurrently:
    [code-generator: slice-a]  ──→  [qa-auditor: slice-a]  ─┐
    [code-generator: slice-b]  ──→  [qa-auditor: slice-b]  ─┤→  commit + push
    [code-generator: slice-c]  ──→  [qa-auditor: slice-c]  ─┘
    ↓
HUMAN TESTING GATE — exact run commands + expected result; you confirm before next phase
    ↓
(issue → qa-auditor classifies SPEC-vs-CODE → code-generator fixes → re-gate)
    ↓
repeat per phase → SHIP
```

Phase 1 is the smallest first-time-right win — real on the tested path, with labelled stubs for everything coming later. Each later phase wires one more stub into real functionality.

---

## Repo Layout

```
src/                ← baseline agent (FastAPI + LangGraph + SQLite, Anthropic/Gemini)
  api/              ← FastAPI routers (create_app, health, runs)
  config/           ← Pydantic BaseSettings
  db/               ← SQLAlchemy models + session
  domain/           ← Pydantic request/response models
  graph/            ← LangGraph nodes, edges, state, runner  ← CAPABILITY SLOT
  llm/              ← LLM client + providers/ (anthropic, gemini)
  prompts/          ← prompt templates (.md)
  observability/
frontend/           ← Next.js static export (served by FastAPI at /app)
tests/
  unit/             ← passes with no API key
  integration/      ← requires real key in .env
spec/               ← your spec: roadmap, architecture, capabilities/, data, api, ui, agent
harness/
  rules/            ← ai-agents, git, secret-hygiene
  patterns/         ← spec-driven, phases, project-layout, tech-stack, code, test-driven, ui-ux, agentic-ai, engineering-practices
.claude/
  skills/           ← /zero-shot-build, /zero-shot-fix, /zero-shot-sync
  agents/           ← agent-builder, spec-writer, code-generator, qa-auditor
CLAUDE.md
pyproject.toml
alembic.ini        ← Alembic migrations (alembic/)
agent.py            ← verify setup (default); --run to start the server
.env.example
```

**The analysis pipeline** (Phase 1, replacing the baseline `transform_text` slot):
- `src/analysis/` — `store.py` (upload/profile/load), `privacy.py` (the LLM choke point), `executor.py` (restricted local pandas execution)
- `src/graph/` — the LangGraph `plan → generate_code → execute_locally → verify → answer` graph + SSE runner
- `src/api/` — `datasets.py` (upload), `analyses.py` (SSE ask + history)
- `src/prompts/` — `plan.md`, `generate_code.md`, `answer.md`
- `frontend/src/app/page.tsx` — the chat UI

Everything else (graph wiring, API, DB, settings, tests) is already working.

---

## Running the Data Analysis Agent

All commands run from the **repo root**.

```bash
cp .env.example .env
# edit .env: set your Anthropic key —
#   AGENT_ANTHROPIC_API_KEY=<your key>
# (the provider is auto-detected from whichever key is set)
uv sync --extra dev                    # install deps incl. pandas, numpy, pytest

uv run alembic upgrade head            # create the SQLite tables (datasets, analysis_runs)
cd frontend && pnpm install && pnpm build && cd ..   # build the static UI into frontend/out
uv run python -m src                   # start FastAPI + the UI on port 8001
```

Then open **`http://localhost:8001/app/`**, upload a CSV, and ask a question
(e.g. "What is the total revenue by region?"). You will see live step chips
(Planning → Writing code → Running locally → Verifying → Answering), a
plain-language answer, and a collapsible panel with the exact pandas code.

| URL | What |
|-----|------|
| `http://localhost:8001/app/` | **UI** — upload → ask → answer |
| `http://localhost:8001/health` | API health check |
| `http://localhost:8001/docs` | Interactive API docs (Swagger) |

### Key endpoints (Phase 1)

- `POST /datasets` — multipart CSV upload; returns the schema+sample profile.
- `POST /analyses` — `{dataset_id, question}`; streams SSE `step` events then a terminal `done` (or `error`).
- `GET /analyses/{run_id}` — a persisted run (question, code, result summary, answer, trace).
- `GET /analyses?dataset_id=&limit=` — run history, newest first.

### Environment variables (`AGENT_` prefix)

| Var | Default | Purpose |
|-----|---------|---------|
| `AGENT_ANTHROPIC_API_KEY` | — | Anthropic key (required) |
| `AGENT_LLM_MODEL` | `claude-sonnet-4-6` | Override the model |
| `AGENT_SAMPLE_ROWS` | `5` | Max sample rows sent to the LLM |
| `AGENT_SAMPLE_CELL_CHARS` | `200` | Per-cell char cap on samples/results |
| `AGENT_RESULT_ROWS` | `20` | Max rows in a bounded result summary |
| `AGENT_EXEC_TIMEOUT` | `30` | Wall-clock timeout (s) for local code |
| `AGENT_MAX_RETRIES` | `3` | Refine loops before best-guess-with-flag |
| `AGENT_MAX_UPLOAD_MB` | `500` | Reject uploads larger than this |
| `AGENT_UPLOADS_DIR` | `./data/uploads` | On-disk raw-file store (git-ignored) |

Set `LANGCHAIN_TRACING_V2=true` (+ `LANGCHAIN_API_KEY`) to enable LangSmith
tracing; otherwise tracing is a no-op and each run is logged to stdout.

Tests:

```bash
uv run pytest tests/unit/ -q          # no key needed
uv run pytest tests/ -q               # requires real Anthropic key in .env
```

---

## Rules AI Agents Follow

Full rules in `harness/rules/ai-agents.md`. Summary:

- Read the full spec before writing any code
- Never skip a phase; commit every logical unit
- Tests run against the real LLM/API using keys from `.env` — stubbed runs do not count as passing
- Each phase is tested by the human before the next phase starts
- The build record is git history + the PR + the per-phase test-handoffs

---

## FAQ

**What if I already have a stack in mind?**
State it in the idea: `/zero-shot-build [idea] — use Python + FastAPI + PostgreSQL`. Stack choices are binding.

**What if something breaks?**
Run `/zero-shot-fix [what's broken]` — qa-auditor classifies the problem (SPEC vs CODE), the right generator fixes it, qa-auditor re-gates.

**What if spec and code drift?**
Run `/zero-shot-sync` — qa-auditor classifies each divergence, generators fix, spec wins.
