# Capability: Column / Business Annotations

## What It Does
Lets the user attach a note about a column's business meaning to any source (file or DB table), and feeds those user-authored notes into the agent's LLM context so generated code and answers reflect real-world semantics — without exposing any data.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| source_id | uuid | `PUT .../annotation` path | yes |
| table_name | string | path (DB sources) | no |
| column | string | path | yes |
| note | string | `PUT .../annotation` body | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| annotation | JSON `{source_id, table_name, column, note}` | `ColumnAnnotationRow` + response |
| annotations in prompt | text | `privacy.render_context` context for LLM nodes |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite | upsert one note per `(source_id, table_name, column)` | 500 via `api_error` |
| Anthropic (via privacy choke point) | receives relevant annotations as short user-authored text | node sets `error` → `handle_error` |

## Business Rules
- Annotations are **user-authored text** about columns — privacy-safe; they are injected via the single choke point (`privacy.render_context`), never bypassing it.
- One annotation per `(source_id, table_name, column)`; `PUT` upserts.
- Only annotations for the selected source(s) of a run are included, keeping context small.

## Success Criteria
- [ ] Annotating `amt` as "net amount in paise" changes a subsequent answer to report rupees/paise correctly (the note demonstrably reaches the model).
- [ ] The annotation persists (`GET /sessions/{id}` returns it) and survives a restart.
- [ ] A payload-capture test confirms the annotation text appears in the outbound prompt and no raw data is added alongside it.
