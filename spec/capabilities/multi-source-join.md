# Capability: Multi-source Auto-pick / Join / Compare

## What It Does
Answers a single question that targets several sources (files and/or DB connections) — auto-picking the relevant source, or joining/comparing across sources — while preserving the privacy invariant and the memory bound by reducing each source to a bounded intermediate on its own turf, then combining locally.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| question | string | `POST /analyses` | yes |
| source_ids | list[uuid] (files/connections) | `POST /analyses` | no (defaults to session sources) |
| session_id | uuid | `POST /analyses` | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| selected_sources / multi flag | list / bool | `AgentState` + `AnalysisRunRow.source_ids_json` |
| per-source code (pandas/SQL) + combine snippet | text | `AnalysisRunRow.generated_code` (code panel) |
| bounded result summary + answer | JSON / string | SSE `done` + `AnalysisRunRow` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Anthropic (via privacy choke point) | `select_sources` picks/plans; `generate_code` writes per-source code + combine (schema+samples+annotations+history ONLY) | node sets `error` → `handle_error` |
| File source / DB source | reduce each to a bounded intermediate (pandas-local / SQL-pushdown) | caught → `execution_result.error` → retry |

## Business Rules
- **Privacy + memory bound:** each source is reduced **where it lives** — a file reduced locally, a DB aggregated via pushdown — to a **bounded** intermediate (≤`AGENT_RESULT_ROWS`). A local pandas `combine_code` snippet joins/compares those bounded intermediates and assigns `result`, itself bounded. Full tables never meet in memory; nothing beyond schema/samples/summaries reaches the LLM.
- `select_sources` auto-picks a single source when the question targets one; selects several + a decompose-then-combine plan when it spans sources.
- Cross-source joins operate on **aggregated/reduced** intermediates (analyst-style compare), not a full row-level cross product of two large sources.

## Success Criteria
- [ ] "Compare revenue in the CSV to targets in the DB" selects both sources, pushes the DB aggregation down, combines locally, and the reported comparison matches independent per-source computations.
- [ ] With several loaded sources, a single-source question auto-picks the correct one (no combine block generated).
- [ ] A payload-capture test proves each source contributes only schema + ≤N samples to the prompt; no raw rows and no DSN cross the boundary.
- [ ] A multi-source run against a seeded large SQLite table returns a bounded result even though the source table exceeds `AGENT_SQL_MAX_ROWS` (sample-vs-full answers would differ).
