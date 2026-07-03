# Capability: Persist Run History (Audit Trail)

## What It Does
Writes every analysis run — question, generated code, result summary, step trace, timestamps, and token/cost fields — to the local SQLite DB, forming a retrievable audit trail.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| final AgentState | dict | `finalize` / `handle_error` node | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| AnalysisRunRow | DB row | `analysis_runs` table |
| run detail | JSON | `GET /analyses/{run_id}` |
| run list | JSON | `GET /analyses` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite (SQLAlchemy) | insert/update AnalysisRunRow | log + 500 on read; the streamed answer is not lost |

## Business Rules
- A row is created at ask time (`status="running"`) and finalized to `completed` or `failed`.
- Persisted fields: dataset_id, question, plan, generated_code, result_summary_json, answer, status, low_confidence, retry_count, step_trace_json, prompt_tokens, completion_tokens, cost_usd, error_message, timestamps.
- Token/cost captured from the real Anthropic response `usage` even though the UI displays them only in Phase 2.
- History is unbounded in Phase 1 (personal tool); the user prunes manually.
- Raw dataset contents are never written to this table — only the question, code, and bounded summary.

## Success Criteria
- [ ] After a completed ask, `GET /analyses/{run_id}` returns the question, generated_code, result_summary, answer, status=`completed`, and a created_at timestamp.
- [ ] `GET /analyses` lists recent runs newest-first, filterable by `dataset_id`.
- [ ] A failed run is persisted with `status="failed"` and an `error_message`.
- [ ] `prompt_tokens`/`completion_tokens`/`cost_usd` are populated (non-null) from the real Anthropic response.
