# Capability: Ask a Question → Local-Execution Answer

## What It Does
Answers a natural-language question about a loaded dataset by having Claude write pandas code from **schema + samples only**, executing that code **locally against the full file**, verifying the result, and returning a plain-language answer with the key numbers — never sending raw data to the LLM.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id | uuid | `POST /analyses` body | yes |
| question | string | `POST /analyses` body | yes |
| dataset profile (schema + samples) | JSON | `datasets` table / store | yes (loaded server-side) |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| answer | string | SSE `done` event → UI |
| generated_code | string | SSE `done` + code panel |
| result_summary | JSON (bounded) | SSE `done` + persisted |
| low_confidence | bool | SSE `done` → ⚠ badge |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic (via privacy choke point) | plan / generate_code / answer — schema+samples ONLY | node sets `error` → `handle_error` → SSE `error` |
| Local executor | run generated pandas on full DataFrame, restricted namespace + timeout | captured → retry/refine loop (bounded) → best-guess-with-flag |
| Dataset store | load full DataFrame by dataset_id | file-load error → `handle_error` |

## Business Rules
- **Privacy invariant:** every LLM prompt is built by `src/analysis/privacy.py` and contains only schema, ≤N sample rows, and (for the answer node) a bounded result summary. The full DataFrame never enters an LLM prompt.
- Trivial asks take the fast path (skip `plan`).
- Generated code runs in a restricted namespace (no import/open/network/fs-escape) with a wall-clock timeout (`AGENT_EXEC_TIMEOUT`, default 30s); it must assign to `result`.
- Execution error or failed verification loops back to `generate_code` up to `AGENT_MAX_RETRIES` (default 3), then answers with `low_confidence=True` explaining what it tried.
- Verification is deterministic (group counts ≤ row_count, no unexpected all-null, finite totals).
- The reported numbers come from local execution, not from the LLM's imagination.

## Success Criteria
- [ ] Asking "total revenue by region" on a known CSV returns an answer whose numbers equal a direct pandas `groupby(...).sum()` on the full file.
- [ ] A payload-capture test proves the outbound Anthropic request contains the schema and ≤N sample rows and **none** of the sentinel values planted in non-sampled rows.
- [ ] A question that first produces failing code recovers via the refine loop and still answers (or answers with `low_confidence` after max retries), without a 500 to the user.
- [ ] Generated code containing `import`/`open`/network calls is rejected by the executor pre-check before running.
- [ ] The answer, generated code, and bounded result summary reach the UI via the SSE `done` event.
