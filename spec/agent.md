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
| `plan` | Anthropic | `claude-sonnet-4-6` | Reasoning about the question + schema; skipped on fast path. |
| `generate_code` | Anthropic | `claude-sonnet-4-6` | Code generation quality matters most here. |
| `answer` | Anthropic | `claude-sonnet-4-6` | Faithful plain-language phrasing of computed numbers. |
| `execute_locally`, `verify` (numeric checks) | — | none | Deterministic local Python; no LLM. |

Model is env-configurable (`AGENT_LLM_MODEL`). Phase 2 may route the fast-path/trivial asks to a cheaper model; Phase 1 uses one model everywhere. Provider auto-detected from `AGENT_ANTHROPIC_API_KEY` (`src/llm/client.py`).

**Fallback behaviour:** `src/llm` retries transient Anthropic errors (429/5xx) with bounded exponential backoff. On exhaustion the calling node sets `state["error"]` and the graph routes to `handle_error`, which persists the run as `failed` and emits an SSE `error` event. This is production resilience, not a test stub — tests call the real API with keys from `.env`.

**Prompt strategy:** system/user split. System prompts are `.md` files in `src/prompts/` (`plan.md`, `generate_code.md`, `answer.md`). The **user** content is always built by `src/analysis/privacy.py` and contains only schema + samples (+ result summary for `answer`). `generate_code` is instructed to return a fenced Python block that assigns to `result` using the provided `df`; the code is extracted by regex and never `read_*`s a file. Verification is deterministic Python (no structured-output LLM call in Phase 1).

---

## Tools & Tool Calling

Phase 1 uses **no LLM tool-calling**; the "tools" are deterministic graph nodes the orchestration invokes in a fixed topology. The one privileged operation is local code execution.

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `local_executor` | Runs generated pandas code against the full DataFrame in a restricted namespace with a timeout | `code: str`, `df: DataFrame` | `result` value + captured stdout + error | None outside process; no network, no fs writes (by construction) |
| `profile_dataset` | Loads the file and computes schema + N samples + row count | `dataset_id` | `DatasetMeta` | Reads local file only |
| `persist_run` | Writes the audit-trail row | final state | `AnalysisRunRow.id` | DB write |

**Tool selection strategy:** rule-based routing via graph edges (no LLM tool choice). `execute_locally` always runs the code from `generate_code`.

**Tool failure handling:** executor errors are caught, recorded in `state["execution_result"].error`, and routed back to `generate_code` (bounded retries) → best-guess-with-flag. DB write failure in `finalize` logs + surfaces a 500 but does not lose the streamed answer.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                          # set at initialisation (runner)
    dataset_id: str                      # set at initialisation

    # Input
    question: str                        # from the ask request
    dataset_meta: dict                   # {columns, dtypes, sample_rows, row_count} — schema+samples ONLY (from store.profile)

    # Pipeline data (populated progressively by nodes)
    is_trivial: bool                     # set by plan-router pre-check; drives fast path
    plan: str | None                     # set by `plan` (None on fast path)
    generated_code: str                  # set by `generate_code`
    execution_result: dict | None        # {result_summary, stdout, error} — set by `execute_locally` (result stays LOCAL)
    verification: dict | None            # {passed: bool, notes: str} — set by `verify`
    retry_count: int                     # incremented on refine loop; capped by AGENT_MAX_RETRIES (default 3)
    low_confidence: bool                 # set true when retries exhausted → best-guess-with-flag

    # Output
    answer: str                          # final plain-language answer (from `answer`)
    step_trace: list                     # [{step, status, detail, ts}] — appended by every node for the UI/audit
    tokens: dict                         # {prompt, completion} accumulated (0 in P1 display; recorded)
    cost_usd: float                      # accumulated (recorded in P1, displayed in P2)

    # Control
    error: str | None                    # set by any node on fatal failure
    status: str                          # "running" | "completed" | "failed"
```

> Note: `dataset_meta` carries schema + bounded samples ONLY. The full DataFrame is loaded inside `execute_locally` from the dataset store by `dataset_id` and is **never** placed in state, so it can never leak into an LLM prompt.

---

## Nodes / Steps

### `plan_router` (conditional entry logic, not a node — see edges)
A cheap deterministic pre-check decides `is_trivial`: if the question matches trivial patterns (single-column count/sum/mean/min/max/"how many rows", no join/group phrasing) it sets the fast path (skip `plan`). Implemented as the entry conditional edge reading `question` + `dataset_meta`.

### `plan`
**Reads from state:** `question`, `dataset_meta`
**Writes to state:** `plan`, `step_trace`, `tokens`, `cost_usd`
**LLM call:** yes — `src/prompts/plan.md` system + user context from `privacy.render_context` (schema+samples ONLY). Output: a short natural-language plan.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic | plan the analysis | fatal → set `error` → `handle_error` |
**Behaviour:** produces a brief plan of how to answer (which columns, what aggregation). Skipped on the fast path.

### `generate_code`
**Reads from state:** `question`, `dataset_meta`, `plan`, `execution_result` (on retry: the prior error), `retry_count`
**Writes to state:** `generated_code`, `step_trace`, `tokens`, `cost_usd`, `retry_count`
**LLM call:** yes — `src/prompts/generate_code.md` system + user context (schema+samples ONLY, plus the plan and, on retry, the previous code + error message — never raw data). Output: a fenced Python block assigning `result`.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic | write pandas code | fatal → set `error` → `handle_error` |
**Behaviour:** emits pandas code that uses the injected `df` and assigns the answer to `result`. On a retry it receives the failing code + error to fix it.

### `execute_locally`
**Reads from state:** `generated_code`, `dataset_id`
**Writes to state:** `execution_result`, `step_trace`
**LLM call:** no.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Dataset store | load full DataFrame by `dataset_id` | fatal → set `error` (file missing) |
| local_executor | run code in restricted namespace, timeout | caught → `execution_result.error` set, routes to retry |
**Behaviour:** loads the **full** file to a DataFrame, runs the generated code in the restricted namespace (`src/analysis/executor.py`) with a wall-clock timeout, captures `result` + stdout. Builds a **bounded** `result_summary` (scalars pass; tables truncated to `AGENT_RESULT_ROWS`) — this summary is the only computed data allowed onward to the LLM.

### `verify`
**Reads from state:** `execution_result`, `dataset_meta`
**Writes to state:** `verification`, `step_trace`
**LLM call:** no (deterministic checks in Phase 1).
**Behaviour:** runs sanity checks on the result summary — e.g. group counts don't exceed row_count, no unexpected all-null result, totals are finite/non-negative where implied. Sets `verification.passed`. On failure (or if `execution_result.error` is set) the edge routes back to `generate_code` while `retry_count < AGENT_MAX_RETRIES`; once exhausted it sets `low_confidence` and proceeds to `answer`.

### `answer`
**Reads from state:** `question`, `dataset_meta`, `execution_result.result_summary`, `low_confidence`
**Writes to state:** `answer`, `step_trace`, `tokens`, `cost_usd`
**LLM call:** yes — `src/prompts/answer.md` system + user context (schema+samples + the **bounded** result summary ONLY). Output: plain-language answer with the key numbers; if `low_confidence`, it flags the uncertainty and notes what was tried.
**Behaviour:** phrases the computed numbers in plain English. Does not recompute; only reports the summary.

### `finalize`
**Reads from state:** all output fields
**Writes to state:** `status="completed"`
**Behaviour:** persists `AnalysisRunRow` (question, generated_code, result summary, step trace, tokens/cost, timestamp) and emits the terminal SSE `done` event.

### `handle_error`
**Reads from state:** `error`, `run_id`
**Behaviour:** sets `status="failed"`, persists the run with `error_message`, logs with `run_id`, emits SSE `error`, terminates.

---

## Graph / Flow Topology

```
START
  │
  ▼
(entry router: is_trivial?)
  │  trivial ─────────────┐
  │  non-trivial          │
  ▼                       │
plan ──(error)──► handle_error ──► END
  │                       │
  └───────────┬───────────┘
              ▼
       generate_code ──(error)──► handle_error ──► END
              │
              ▼
      execute_locally ──(load error)──► handle_error ──► END
              │
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
     finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| START (entry) | `is_trivial` is True | `generate_code` |
| START (entry) | `is_trivial` is False | `plan` |
| `plan` | `state["error"]` is not None | `handle_error` |
| `plan` | else | `generate_code` |
| `generate_code` | `state["error"]` is not None | `handle_error` |
| `generate_code` | else | `execute_locally` |
| `execute_locally` | `state["error"]` is not None (file load) | `handle_error` |
| `execute_locally` | else | `verify` |
| `verify` | `verification.passed` and no exec error | `answer` |
| `verify` | (failed or exec error) and `retry_count < MAX` | `generate_code` |
| `verify` | (failed or exec error) and `retry_count >= MAX` | `answer` (with `low_confidence=True`) |
| `answer` | always | `finalize` |
| `finalize` / `handle_error` | always | `END` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state | All in-progress data (schema, plan, code, result summary, trace) |
| **Across runs** | SQLite | `AnalysisRunRow` audit trail; `DatasetRow` metadata (Phase 1). Cross-day sessions + annotations in Phase 3. |
| **Conversation** | `messages` in state + persisted per session (Phase 3) | Phase 1: single-turn per ask (each analysis is independent — the primary journey is upload→ask→answer, not multi-turn chat). Conversation history across turns/days is a **Phase 3** capability. |

> **Assumed:** Phase 1 is single-turn (each question answered against the dataset independently, no cross-question memory). This is justified because the Phase-1 primary journey is "upload → ask → correct answer", and each answer is fully determined by the dataset + that one question; conversational follow-up memory is delivered with sessions in Phase 3. Flagged for confirmation.

**Context window management:** the LLM context is intrinsically small (schema + ≤5 sample rows + a ≤20-row result summary), so no summarisation/RAG is needed. Bounding is enforced in `privacy.py`.

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
- **Parallel nodes within a run:** none in Phase 1 (linear pipeline).
- **Checkpointing:** none in Phase 1 (short runs, no human-in-the-loop). Add a saver only if Phase 3 sessions need mid-run resume.

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import (
    plan, generate_code, execute_locally, verify, answer, finalize, handle_error,
)
from graph.edges import entry_router, after_plan, after_generate, after_execute, after_verify

def _build_graph():
    g = StateGraph(AgentState)
    for name, fn in [
        ("plan", plan), ("generate_code", generate_code),
        ("execute_locally", execute_locally), ("verify", verify),
        ("answer", answer), ("finalize", finalize), ("handle_error", handle_error),
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
    g.add_edge("answer", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()

agentic_ai = _build_graph()   # keep the exported name the skeleton uses
```
