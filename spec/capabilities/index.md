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

### Phase 2 (built)

| Capability | Phase |
|-----------|-------|
| Auto-profile insights + 2–3 follow-up suggestions | 2 |
| Interactive, downloadable charts (auto/user-requested) | 2 |
| Per-query token/cost + running daily total | 2 |
| Exports: cleaned dataset (CSV/Parquet), code, shareable report | 2 |

### Phase 3 (final phase — wires the remaining stubs)

| Capability | File |
|-----------|------|
| Live DB connections (Postgres/MySQL/SQLite) with SQL pushdown/sampling | [db-connection.md](db-connection.md) |
| Non-CSV formats (Excel/JSON/Parquet/PDF/log) | [non-csv-formats.md](non-csv-formats.md) |
| Persistent cross-day sessions + conversation memory | [sessions-memory.md](sessions-memory.md) |
| Column/business annotations | [annotations.md](annotations.md) |
| Multi-source auto-pick / join / compare | [multi-source-join.md](multi-source-join.md) |

### Phase 4 (built)

| Capability | File |
|-----------|------|
| Data workbench: profile tiles (PK/FK) + local DuckDB SQL query box | [data-workbench.md](data-workbench.md) |

### Phase 5 (deferred — stubbed in Phase 4)

| Capability | File |
|-----------|------|
| Dashboard + interactive 3D charts + cloud connectors (opt-in) | [dashboard-cloud.md](dashboard-cloud.md) |

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer creates a new `<name>.md`, updates this index, flags dependencies, and self-reviews fit against the architecture and data model.

## Capability File Template

Each file answers: What It Does, Inputs, Outputs, External Calls, Business Rules, Success Criteria.
