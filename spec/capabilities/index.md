# Capabilities Index

> One file per capability. Each describes exactly one discrete thing the agent can do.

---

## Capabilities in This Project

### Phase 1 (built)

| Capability | File |
|-----------|------|
| Upload & profile a CSV (schema + samples only) | [upload-csv.md](upload-csv.md) |
| Ask a question → local execution answer (privacy invariant) | [ask-question-local-execution.md](ask-question-local-execution.md) |
| Show the generated code | [show-generated-code.md](show-generated-code.md) |
| Live step-by-step streaming | [live-step-streaming.md](live-step-streaming.md) |
| Persist run history (audit trail) | [persist-run-history.md](persist-run-history.md) |

### Deferred (later phases — shipped as labelled stubs in Phase 1)

| Capability | Phase |
|-----------|-------|
| Auto-profile insights + 2–3 follow-up suggestions | 2 |
| Interactive, downloadable charts (auto/user-requested) | 2 |
| Per-query token/cost + running daily total | 2 |
| Exports: cleaned dataset (CSV/Parquet), code, shareable report | 2 |
| Live DB connections (Postgres/MySQL/SQLite) with SQL pushdown/sampling | 3 |
| Non-CSV formats (Excel/JSON/Parquet/PDF/log) | 3 |
| Persistent cross-day sessions + conversation memory | 3 |
| Column/business annotations | 3 |
| Multi-source auto-pick / join / compare | 3 |

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer creates a new `<name>.md`, updates this index, flags dependencies, and self-reviews fit against the architecture and data model.

## Capability File Template

Each file answers: What It Does, Inputs, Outputs, External Calls, Business Rules, Success Criteria.
