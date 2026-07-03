# Capability: Live Step-by-Step Streaming

## What It Does
Streams the agent's progress to the UI in real time — a step event per node (plan → generate_code → execute_locally → verify → answer) — so the user watches the work happen instead of staring at a spinner.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| in-flight AgentState `step_trace` | list | graph nodes during a run | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| SSE `step` events | text/event-stream | UI live-trace chips |
| SSE `done` / `error` terminal event | text/event-stream | UI answer / error |
| persisted step_trace | JSON | `analysis_runs.step_trace_json` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LangGraph streaming | `agentic_ai.stream(..., stream_mode="updates")` yields per-node updates | node error → terminal SSE `error` |

## Business Rules
- Transport is **SSE over the `POST /analyses` response** (`text/event-stream`); the frontend reads `response.body.getReader()` (EventSource cannot POST).
- One `step` event per node advance, mapping node name → human label (Planning / Writing code / Running locally / Verifying / Answering), with `status` (running|done) and a short `detail`.
- On the fast path the `plan` step is emitted as skipped.
- The stream ends with exactly one terminal event: `done` (carries answer + code + summary + trace) or `error`.
- Step events carry no raw data — only labels, status, and small details (e.g. "Ran locally on 10,432 rows").

## Success Criteria
- [ ] During an ask, the client receives ordered `step` events for each executed node, then a single terminal `done`.
- [ ] The UI shows chips flipping running → done in order as events arrive (verified by the Playwright E2E test).
- [ ] A failing run emits a terminal `error` event (not a silent hang) and the client renders it.
- [ ] The persisted `step_trace_json` matches the streamed sequence.
