# Agent

---

## Agent Architecture Pattern

| Pattern | Use when |
|---------|----------|
| **Single-agent loop** | One LLM drives a deterministic tool-call loop. No branches, no handoffs. |
| **Graph (LangGraph)** | Multi-step pipeline with conditional edges, checkpointing, or parallel nodes. |
| **Multi-agent** | Specialised sub-agents with distinct roles; orchestrator routes between them. |
| **Supervisor** | One supervisor LLM dispatches to worker agents based on task type. |
| **Human-in-the-loop** | Execution pauses at defined checkpoints for user review or approval. |

**Chosen:** **Graph (LangGraph).** The analysis is a multi-step pipeline — plan → generate code → execute locally → verify → answer — with a conditional **fast-path** (trivial asks skip planning) and a conditional **retry/refine** loop (execution error or failed verification loops back to generate_code, bounded). A graph expresses these branches and lets us stream a step event per node.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `select_sources` (Phase 3) | Anthropic | `claude-sonnet-4-6` | Pick the relevant source(s) for the question and, for multi-source, produce a join/compare plan — from each source's schema+samples ONLY. |
| `plan` | Anthropic | `claude-sonnet-4-6` | Reasoning about the question + schema; skipped on fast path. |
| `generate_code` | Anthropic | `claude-sonnet-4-6` | Code generation quality matters most here. Phase 3: emits pandas (file source) OR SQL (DB source) per selected source + an optional local combine snippet. |
| `answer` | Anthropic | `claude-sonnet-4-6` | Faithful plain-language phrasing of computed numbers. |
| `chart_spec` (Phase 2) | Anthropic | `claude-sonnet-4-6` | Emits a Vega-Lite v5 spec from schema + the **bounded** result summary ONLY. Conditional (chartable results only); never fails the run. |
| `execute_locally`, `verify` (numeric checks) | — | none | Deterministic local Python / DB-pushdown; no LLM. |

Model is env-configurable (`AGENT_LLM_MODEL`). Phase 2 may route the fast-path/trivial asks to a cheaper model; Phase 1 uses one model everywhere. Provider auto-detected from `AGENT_ANTHROPIC_API_KEY` (`src/llm/client.py`).

**Fallback behaviour:** `src/llm` retries transient Anthropic errors (429/5xx) with bounded exponential backoff. On exhaustion the calling node sets `state["error"]` and the graph routes to `handle_error`, which persists the run as `failed` and emits an SSE `error` event. This is production resilience, not a test stub — tests call the real API with keys from `.env`.

**Prompt strategy:** system/user split. System prompts are `.md` files in `src/prompts/` (`plan.md`, `generate_code.md`, `answer.md`; `chart.md` in Phase 2; `select_sources.md` in Phase 3). The **user** content is always built by `src/analysis/privacy.py` and contains only schema + samples (+ result summary for `answer`/`chart_spec`, + annotations + bounded conversation history in Phase 3). `generate_code` is instructed to return a fenced Python block that assigns to `result` using the provided `df` (file source), or a read-only SQL block (DB source); the code is extracted by regex and never `read_*`s a file. Verification is deterministic Python (no structured-output LLM call).

---

## Tools & Tool Calling

Phase 1 uses **no LLM tool-calling**; the "tools" are deterministic graph nodes the orchestration invokes in a fixed topology. The one privileged operation is local code execution.

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `local_executor` | Runs generated pandas code against the full DataFrame in a restricted namespace with a timeout | `code: str`, `df: DataFrame` | `result` value + captured stdout + error | None outside process; no network, no fs writes (by construction) |
| `db_source.execute` (Phase 3) | Runs generated **read-only SQL** pushed down to the connected DB via SQLAlchemy; fetches a bounded intermediate | `sql: str`, `connection_id` | bounded result rows + error | Read-only query on the DB (rejects DDL/DML); full table never leaves the DB |
| `profile_dataset` | Loads the file (CSV/Excel/JSON/Parquet/PDF/log in Phase 3) and computes schema + N samples + row count | `dataset_id` | `DatasetMeta` | Reads local file only |
| `introspect_db` (Phase 3) | Introspects a DB connection's schema (tables/columns/types) + a `LIMIT N` sample via the SQLAlchemy inspector | `connection_id` | `SourceMeta` (schema+sample) | Read-only DB metadata + bounded sample query |
| `persist_run` | Writes the audit-trail row (+ Phase-3 session turn) | final state | `AnalysisRunRow.id` | DB write |

**Tool selection strategy:** rule-based routing via graph edges (no LLM tool choice). `execute_locally` always runs the code from `generate_code`.

**Tool failure handling:** executor errors are caught, recorded in `state["execution_result"].error`, and routed back to `generate_code` (bounded retries) → best-guess-with-flag. DB write failure in `finalize` logs + surfaces a 500 but does not lose the streamed answer.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                          # set at initialisation (runner)
    dataset_id: str                      # PRIMARY / single source (Phase 1); still set in Phase 3
    session_id: str                      # Phase 3 — the session this run belongs to

    # Input
    question: str                        # from the ask request
    dataset_meta: dict                   # {dataset_id, filename, columns, dtypes, sample_rows, row_count} — schema+samples ONLY
    want_chart: bool                     # Phase 2 — request-level flag: force chart generation

    # Phase 3 — multi-source + memory + annotations (all schema/samples/prose ONLY)
    sources: list                        # registered sources in scope: [{source_id, kind:"file"|"db", name, columns, sample_rows, row_count|est}] — schema+samples ONLY
    selected_sources: list               # [source_id, ...] chosen by `select_sources`
    is_multi_source: bool                # True when >1 source selected → join/compare path
    source_plan: dict | None             # {per_source:[{source_id, subtask}], combine:str} — from `select_sources`
    conversation: list                   # prior turns [{role, content}] from the session (privacy-safe prose), bounded to last AGENT_MEMORY_TURNS
    annotations: dict                    # {source_id: {column: note}} — user-authored column/business notes (privacy-safe text)

    # Pipeline data (populated progressively by nodes)
    is_trivial: bool                     # set by the entry router pre-check; drives fast path (single-source only)
    plan: str | None                     # set by `plan` (None on fast path)
    generated_code: str                  # display code (single source) — set by `generate_code`
    per_source_code: dict                # Phase 3 — {source_id: {lang:"pandas"|"sql", code}} — set by `generate_code`
    combine_code: str | None             # Phase 3 — local pandas snippet joining/comparing bounded per-source intermediates (None for single source)
    execution_result: dict | None        # {result_summary, stdout, error} — set by `execute_locally` (result stays LOCAL / DB-bounded)
    verification: dict | None            # {passed: bool, notes: str} — set by `verify`
    retry_count: int                     # incremented on refine loop; capped by AGENT_MAX_RETRIES (default 3)
    low_confidence: bool                 # set true when retries exhausted → best-guess-with-flag

    # Output
    answer: str                          # final plain-language answer (from `answer`)
    chart_spec: dict | None              # Phase 2 — Vega-Lite v5 spec with bounded inline data (or None) — set by `chart_spec`
    step_trace: list                     # [{step, status, detail, ts}] — appended by every node for the UI/audit
    tokens: dict                         # {prompt, completion} accumulated
    cost_usd: float                      # accumulated (recorded in P1, displayed from P2)

    # Control
    error: str | None                    # set by any node on fatal failure
    status: str                          # "running" | "completed" | "failed"
```

> Note: `dataset_meta` and each entry of `sources` carry schema + bounded samples ONLY. The full DataFrame (file source) is loaded inside `execute_locally` from the dataset store by `source_id`, and DB-source queries execute **inside the DB** — neither the full file nor any full DB table is ever placed in state, so neither can leak into an LLM prompt. `conversation` holds prior questions + the agent's own prior answers (already privacy-safe prose), and `annotations` holds user-authored text about columns — both safe to send; neither is raw data.

---

## Nodes / Steps

### `entry_router` (conditional entry logic, not a node — see edges)
A cheap deterministic pre-check decides `is_trivial`: if the question matches trivial patterns (single-column count/sum/mean/min/max/"how many rows", no join/group phrasing) **and** exactly one source is in scope, it sets the fast path (skip `plan`). In Phase 3 the graph enters at `select_sources`; `is_trivial` is then evaluated by `after_select` (multi-source is never trivial).

### `select_sources` (Phase 3)
**Reads from state:** `question`, `sources` (each source's schema+samples), `annotations`, `conversation`
**Writes to state:** `selected_sources`, `is_multi_source`, `source_plan`, `dataset_meta` (set to the primary selected source's meta for the single-source path), `step_trace`, `tokens`, `cost_usd`
**LLM call:** yes — `src/prompts/select_sources.md` system + user context built by `privacy.render_context` from **each source's schema + bounded samples ONLY** (plus relevant annotations + bounded conversation history — all privacy-safe text). Output: JSON `{selected:[source_id...], multi:bool, per_source:[{source_id, subtask}], combine:"<how to join/compare>"}`.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic | pick relevant source(s) + plan a join/compare | fatal → set `error` → `handle_error` |
**Behaviour:** with a single source in scope this is a near-noop (selects the only source, `multi=False`) and may be skipped when the request already pins one `dataset_id`. With multiple sources it auto-picks the relevant one, or, when the question spans sources ("compare the CSV to the DB"), selects several and emits a decompose-then-combine plan. Never sees raw rows or a connection string.

### `plan`
**Reads from state:** `question`, `dataset_meta` / selected `sources`, `annotations`, `conversation`, `source_plan`
**Writes to state:** `plan`, `step_trace`, `tokens`, `cost_usd`
**LLM call:** yes — `src/prompts/plan.md` system + user context from `privacy.render_context` (schema+samples + user-authored annotations + bounded prior-turn prose ONLY). Output: a short natural-language plan.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic | plan the analysis | fatal → set `error` → `handle_error` |
**Behaviour:** produces a brief plan of how to answer (which columns, what aggregation, and for multi-source how the per-source results combine). Skipped on the fast path.

### `generate_code`
**Reads from state:** `question`, `dataset_meta` / selected `sources`, `plan`, `source_plan`, `annotations`, `conversation`, `execution_result` (on retry: the prior error), `retry_count`
**Writes to state:** `generated_code` (display), `per_source_code`, `combine_code`, `step_trace`, `tokens`, `cost_usd`, `retry_count`
**LLM call:** yes — `src/prompts/generate_code.md` system + user context (schema+samples + annotations + prior-turn prose ONLY, plus the plan and, on retry, the previous code + error message — never raw data, never a connection string). Output: per selected source, a fenced block whose language is dictated by the source kind — **pandas** (file source, uses the injected `df`) or **SQL** (DB source, a single read-only `SELECT`/`WITH`); plus, for multi-source, a final fenced **pandas** combine block that joins/compares the bounded per-source intermediates and assigns `result`.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic | write pandas / SQL per source (+ combine) | fatal → set `error` → `handle_error` |
**Behaviour:** for a single file source this reduces to Phase-1 behaviour (one pandas block assigning `result`). For a DB source it writes read-only SQL pushed down to the DB. For multi-source it writes one block per source plus a local combine block. On a retry it receives the failing code + error to fix it.

### `execute_locally` (source-type-aware in Phase 3)
**Reads from state:** `per_source_code` (or `generated_code`), `combine_code`, `selected_sources`, `sources`
**Writes to state:** `execution_result`, `step_trace`
**LLM call:** no.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Dataset store | load full DataFrame by `source_id` (file sources) | fatal → set `error` (file missing) |
| DB source (SQLAlchemy engine) | execute read-only SQL **pushed down** to the DB; fetch a bounded intermediate | caught → `execution_result.error` set, routes to retry |
| local_executor | run pandas (per-source + combine) in the restricted namespace, timeout | caught → `execution_result.error` set, routes to retry |
**Behaviour:** for each selected source it runs that source's code **on its own source** — a file source loads the **full** DataFrame and runs pandas locally (`src/analysis/executor.py`); a DB source runs the generated read-only SQL **inside the DB** (`src/analysis/db_source.py`), so the full table never leaves the DB and only a bounded intermediate returns. The per-source intermediates (each already reduced/aggregated and bounded to `AGENT_RESULT_ROWS`) are combined by the local `combine_code` pandas snippet for multi-source. Builds one **bounded** `result_summary` (scalars pass; tables truncated to `AGENT_RESULT_ROWS`) — the only computed data allowed onward to the LLM. `generated_code` for the audit/code panel is the concatenation of the per-source blocks + combine.

### `verify`
**Reads from state:** `execution_result`, `dataset_meta`
**Writes to state:** `verification`, `step_trace`
**LLM call:** no (deterministic checks in Phase 1).
**Behaviour:** runs sanity checks on the result summary — e.g. group counts don't exceed row_count, no unexpected all-null result, totals are finite/non-negative where implied. Sets `verification.passed`. On failure (or if `execution_result.error` is set) the edge routes back to `generate_code` while `retry_count < AGENT_MAX_RETRIES`; once exhausted it sets `low_confidence` and proceeds to `answer`.

### `answer`
**Reads from state:** `question`, `dataset_meta`, `execution_result.result_summary`, `annotations`, `conversation`, `low_confidence`
**Writes to state:** `answer`, `step_trace`, `tokens`, `cost_usd`
**LLM call:** yes — `src/prompts/answer.md` system + user context (schema+samples + the **bounded** result summary + user-authored annotations + bounded prior-turn prose ONLY). Output: plain-language answer with the key numbers; if `low_confidence`, it flags the uncertainty and notes what was tried.
**Behaviour:** phrases the computed numbers in plain English, aware of the conversation so far (follow-ups like "and by month?" resolve against the prior turn). Does not recompute; only reports the summary.

### `chart_spec` (Phase 2 — conditional, after `answer`)
**Reads from state:** `question`, `dataset_meta`, `execution_result.result_summary`, `want_chart`
**Writes to state:** `chart_spec`, `step_trace`, `tokens`, `cost_usd`
**LLM call:** yes (only when reached) — `src/prompts/chart.md` system + user context built by `privacy.render_context` from **schema + the BOUNDED result summary ONLY** (never raw data). Output: a Vega-Lite v5 JSON spec.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic | emit a Vega-Lite v5 chart spec | caught → `chart_spec=None`, **run continues** (charting never fails the run) |
**Behaviour:** runs only when `after_answer` routes here — i.e. the request forced a chart (`want_chart`) or the result is naturally chartable (a non-empty grouped/aggregated `dataframe`/`series`; scalars, empty results, and failed runs are skipped). Validates the returned spec (requires `mark` + `encoding`) and re-bounds any inline `data.values` to `AGENT_RESULT_ROWS` as defense-in-depth. On any failure or a non-chartable result it degrades quietly to `chart_spec=None` and the run proceeds to `finalize`.

### `finalize`
**Reads from state:** all output fields
**Writes to state:** `status="completed"`
**Behaviour:** persists `AnalysisRunRow` (question, generated_code, result summary, chart spec, step trace, tokens/cost, timestamp, and the selected `source_ids`/`session_id`) and, in Phase 3, appends the user question + the agent's answer to the session's conversation (`SessionMessageRow`) so the next turn and a next-day reopen have the thread. Emits the terminal SSE `done` event.

### `handle_error`
**Reads from state:** `error`, `run_id`
**Behaviour:** sets `status="failed"`, persists the run with `error_message`, logs with `run_id`, emits SSE `error`, terminates.

---

## Graph / Flow Topology

Phase-3 topology — `select_sources` is prepended as the entry node; `chart_spec` sits conditionally after `answer` (Phase 2). Everything between `plan` and `verify` is unchanged in shape; `execute_locally` is now source-type-aware internally.

```
START
  │
  ▼
select_sources ──(error)──► handle_error ──► END      (single source: near-noop / skipped)
  │
  ▼
(after_select: is_trivial & single-source?)
  │  trivial ─────────────┐
  │  non-trivial / multi   │
  ▼                        │
plan ──(error)──► handle_error ──► END
  │                        │
  └───────────┬────────────┘
              ▼
       generate_code ──(error)──► handle_error ──► END
              │   (pandas | SQL per source + combine)
              ▼
      execute_locally ──(load/DB fatal error)──► handle_error ──► END
              │   file → pandas-local · DB → SQL-pushdown · multi → local combine
              ▼
           verify
        ┌────┴─────────────────────────┐
   passed│                             │ failed / exec error
        ▼                              ▼
     answer                (retry_count < MAX)? ──yes──► generate_code
        │                              │ no
        │                              ▼
        │                        set low_confidence ──► answer
        ▼
 (after_answer: chartable or want_chart?)
        │  yes ──► chart_spec ──► finalize ──► END
        │  no ───────────────────► finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| START (entry) | always (Phase 3) | `select_sources` |
| `select_sources` | `state["error"]` is not None | `handle_error` |
| `select_sources` | `is_trivial` and single source | `generate_code` |
| `select_sources` | else (non-trivial or multi-source) | `plan` |
| `plan` | `state["error"]` is not None | `handle_error` |
| `plan` | else | `generate_code` |
| `generate_code` | `state["error"]` is not None | `handle_error` |
| `generate_code` | else | `execute_locally` |
| `execute_locally` | `state["error"]` is not None (file load / DB connect fatal) | `handle_error` |
| `execute_locally` | else | `verify` |
| `verify` | `verification.passed` and no exec error | `answer` |
| `verify` | (failed or exec error) and `retry_count < MAX` | `generate_code` |
| `verify` | (failed or exec error) and `retry_count >= MAX` | `answer` (with `low_confidence=True`) |
| `answer` (`after_answer`) | `want_chart` or `is_chartable(state)` | `chart_spec` |
| `answer` (`after_answer`) | else | `finalize` |
| `chart_spec` | always | `finalize` |
| `finalize` / `handle_error` | always | `END` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state | All in-progress data (selected sources, plan, per-source code, result summary, trace) |
| **Across runs** | SQLite | `AnalysisRunRow` audit trail; `DatasetRow` / `ConnectionRow` metadata; `ColumnAnnotationRow` (Phase 3). |
| **Conversation** | `conversation` in state, loaded from `SessionMessageRow` per session (Phase 3) | Phases 1–2: single-turn per ask. Phase 3: the last `AGENT_MEMORY_TURNS` (default 8) prior turns (question + the agent's own answer prose) are loaded into `conversation` and fed to the LLM nodes, so follow-ups and next-day reopens keep context. |

> **Assumed (Phase 1/2, still true):** each Phase-1/2 ask is single-turn. Conversational memory is delivered in Phase 3 via persistent sessions. Flagged for confirmation.

**Conversation memory & the invariant (Phase 3):** what is fed back is *prior questions* and *the agent's prior answers* — both are privacy-safe text (the answers are prose the agent already produced from bounded summaries, never raw rows). No raw data, no full DB table, and no connection string ever enters `conversation`. History is bounded to the last `AGENT_MEMORY_TURNS` turns to keep the context small.

**Column annotations (Phase 3):** `annotations` is user-authored text describing columns / business meaning (e.g. "`amt` = net amount in paise"). It is safe to send and is injected into every LLM node's context via `privacy.render_context`, keyed to the selected source(s).

**Context window management:** the LLM context is intrinsically small (schema + ≤5 sample rows per source + a ≤20-row result summary + a handful of short prior turns + short annotations), so no summarisation/RAG is needed. Bounding is enforced in `privacy.py`.

---

## Human-in-the-Loop Checkpoints

None in Phase 1 (fully autonomous per ask). The low-confidence path surfaces a flagged best-guess rather than pausing for input. (Clarify-instead-of-guess is a future enhancement, not Phase 1.)

---

## Error Handling & Recovery

**Node-level:** each node wraps its body in try/except; on a fatal error it returns `{**state, "error": str(exc)}`. Executor errors are non-fatal — captured into `execution_result.error` to drive the retry loop.

**Graph-level (`handle_error`):**
- Reads: `state["error"]`, `state["run_id"]`
- Updates DB: run `status → "failed"`, `error_message`, `completed_at`
- Logs error with `run_id` context (structlog)
- Emits SSE `error` event, terminates the graph

**Resume / retry strategy:** the refine loop re-generates code up to `AGENT_MAX_RETRIES` (default 3) on execution error / failed verification, feeding the prior error back to `generate_code`. No cross-request checkpoint resume in Phase 1 (runs are short).

**Partial failure:** if retries are exhausted, the agent still answers with `low_confidence=True`, explaining what it tried — degrade gracefully rather than abort.

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | One trace per run, one span per node | LangSmith when `LANGCHAIN_TRACING_V2=true`; otherwise a no-op |
| **LLM calls** | Prompt tokens, completion tokens, latency, model, run_id | structlog (stdout), from the Anthropic response `usage` |
| **Node/step events** | step name, status, detail, timestamp | `step_trace` in state → streamed to UI via SSE + persisted |
| **Run outcome** | status, duration, error if any, tokens/cost | SQLite `AnalysisRunRow` + structlog |

Observability is wired in Phase 1, not deferred.

---

## Concurrency Model

- **Run isolation:** each ask is scoped by `run_id`; runs are independent. Single local user → low concurrency; no global lock. The dataset store is read-only during a run.
- **Live step streaming:** the ask endpoint returns `text/event-stream`. The runner drives the graph with LangGraph's streaming (`agentic_ai.stream(initial, stream_mode="updates")`); each yielded node update is mapped to an SSE `step` event (`event: step\ndata: {json}\n\n`), and the terminal state is sent as `event: done`. The frontend consumes the POST response body with `fetch` + a `ReadableStream` reader (EventSource can't POST). SSE chosen over WebSockets for simplicity — one-directional, no extra server.
- **Parallel nodes within a run:** none (linear pipeline). Phase-3 multi-source per-source execution runs sequentially inside the single `execute_locally` node (each source reduced to a bounded intermediate, then combined locally) — no fan-out nodes.
- **Checkpointing:** none — runs are short and each is self-contained. Phase-3 sessions persist the *conversation* (`SessionMessageRow`) and sources across runs/days, but not mid-run graph state; there is no mid-run resume.

---

## Graph Assembly (`src/graph/agent.py`)

The Phase-1/2 assembly (current running code) sets `entry_router` as the conditional entry point and wires `answer → chart_spec | finalize`:

```python
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import (
    plan, generate_code, execute_locally, verify, answer, chart_spec,
    finalize, handle_error,
)
from graph.edges import (
    entry_router, after_plan, after_generate, after_execute, after_verify, after_answer,
)

def _build_graph():
    g = StateGraph(AgentState)
    for name, fn in [
        ("plan", plan), ("generate_code", generate_code),
        ("execute_locally", execute_locally), ("verify", verify),
        ("answer", answer), ("chart_spec", chart_spec),
        ("finalize", finalize), ("handle_error", handle_error),
    ]:
        g.add_node(name, fn)

    g.set_conditional_entry_point(
        entry_router,  # is_trivial → "generate_code" else "plan"
        {"plan": "plan", "generate_code": "generate_code"},
    )
    g.add_conditional_edges("plan", after_plan,
                            {"handle_error": "handle_error", "generate_code": "generate_code"})
    g.add_conditional_edges("generate_code", after_generate,
                            {"handle_error": "handle_error", "execute_locally": "execute_locally"})
    g.add_conditional_edges("execute_locally", after_execute,
                            {"handle_error": "handle_error", "verify": "verify"})
    g.add_conditional_edges("verify", after_verify,
                            {"generate_code": "generate_code", "answer": "answer"})
    g.add_conditional_edges("answer", after_answer,
                            {"chart_spec": "chart_spec", "finalize": "finalize"})
    g.add_edge("chart_spec", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()

agentic_ai = _build_graph()   # keep the exported name the skeleton uses
```

**Phase-3 changes to the assembly** — add the `select_sources` node and make it the entry, folding the `is_trivial` fast-path decision into `after_select`:

```python
from graph.nodes import select_sources
from graph.edges import after_select

    g.add_node("select_sources", select_sources)                 # + node
    g.set_entry_point("select_sources")                          # replaces set_conditional_entry_point
    g.add_conditional_edges("select_sources", after_select, {    # + entry routing
        "handle_error": "handle_error",
        "plan": "plan",
        "generate_code": "generate_code",                        # trivial single-source fast path
    })
    # plan / generate_code / execute_locally / verify / answer / chart_spec edges unchanged.
```

`after_select` returns `"handle_error"` on error, `"generate_code"` when `is_trivial` and a single source is selected, else `"plan"`. `execute_locally` is unchanged at the graph level — its source-type dispatch (pandas-local vs SQL-pushdown vs local combine) is internal.
