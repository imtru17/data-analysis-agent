# Capability: Persistent Cross-Day Sessions + Conversation Memory

## What It Does
Keeps persistent sessions that survive restarts and days: a session owns its datasets, connections, runs, and conversation thread, so reopening the app restores prior messages, loaded/derived sources, and multi-turn context — while still sending only schema + samples + bounded summaries (never raw data) to the LLM.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| title | string | `POST /sessions` | no |
| session_id | uuid | `GET /sessions/{id}`, `POST /analyses` | no |
| question (per turn) | string | `POST /analyses` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| session_id / title | uuid / string | `SessionRow` + responses |
| conversation thread | JSON `[{role, content, run_id, created_at}]` | `SessionMessageRow` → `GET /sessions/{id}` |
| restored datasets/connections | JSON | `GET /sessions/{id}` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite | persist/restore sessions, messages, source links | 500 via `api_error`; a computed answer is still streamed |
| Anthropic (via privacy choke point) | receives last `AGENT_MEMORY_TURNS` prior turns as prose | node sets `error` → `handle_error` |

## Business Rules
- **Privacy in memory:** only prose crosses into `conversation` — user questions and the agent's own answers. No sample rows, no result tables, no DSN. History is bounded to `AGENT_MEMORY_TURNS` (default 8).
- `finalize` appends the user question + the answer as `SessionMessageRow`s (assistant message links `run_id`).
- The runner loads the session's recent turns into `AgentState.conversation`; `plan`/`generate_code`/`answer`/`select_sources` receive them via `privacy.render_context`.
- Reopening a session restores its full thread (each answer's code/chart/trace via its `run_id`) and its sources.
- A run without a `session_id` derives/creates one server-side.

## Success Criteria
- [ ] Ask "total revenue by region", then a follow-up "and just for the West?" — the follow-up resolves against the prior turn (the answer references West without re-stating the whole question).
- [ ] Restart the server and `GET /sessions/{id}` — the prior messages, datasets, and connections (masked) are restored.
- [ ] A payload-capture test proves the conversation sent to the LLM contains only prior questions/answers (prose) — none of the sentinel raw-cell values and no DSN.
- [ ] Only the last `AGENT_MEMORY_TURNS` turns appear in the outbound context when more exist.
