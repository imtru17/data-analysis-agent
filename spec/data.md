# Data Model

---

## Storage Technology

SQLite (`sqlite:///./data/agent.db`) via SQLAlchemy 2.0, migrated with alembic. Chosen because the app is a single-user local tool — SQLite needs no server and lives alongside the data. Raw uploaded files are **not** stored in the DB; they live on the local filesystem under `./data/uploads/` and are referenced by path. The generic DB-driver rule (real driver in gates, never a substitute) lives in `harness/patterns/tech-stack.md`.

## Entities

### Entity: DatasetRow (`datasets`)

Metadata for one uploaded dataset. The raw bytes live on disk; this row carries only metadata + schema/sample **profile** (which is exactly what the LLM is allowed to see).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| filename | Text | yes | Original upload name |
| source_kind | Text | yes | `"csv"` (P1); `"excel"`/`"json"`/`"parquet"`/`"pdf"`/`"log"` (P3 file sources); default `"csv"`. DB sources are `ConnectionRow`, not here. |
| file_path | Text | yes | Relative path under `./data/uploads/` (`<dataset_id>.<ext>`) — never the contents |
| row_count | Integer | yes | Total rows in the full file |
| schema_json | Text (JSON) | yes | Ordered `[{name, dtype}]` — column names + dtypes |
| sample_rows_json | Text (JSON) | yes | ≤ `AGENT_SAMPLE_ROWS` sample rows, cell-length capped (the LLM-visible sample) |
| profile_json | Text (JSON) | no | **Phase 2** — rich per-column stats, computed **locally**, cached; NEVER sent to the LLM |
| followups_json | Text (JSON) | no | **Phase 2** — 2–3 suggested follow-up questions from a schema+samples-only LLM call, cached |
| session_id | Text (FK→sessions.id) | no | Null in P1; links to a session in P3 |
| created_at | TIMESTAMP(tz) | yes | Upload time |
| updated_at | TIMESTAMP(tz) | yes | Last touched |

### Entity: AnalysisRunRow (`analysis_runs`)

The audit trail — one row per completed/failed analysis. Replaces the skeleton `RunRow` for the analysis use-case. `RunRow`/`runs` may be dropped or left unused; the analysis pipeline writes here.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (= `run_id`) |
| dataset_id | Text (FK→datasets.id) | yes | Which dataset was queried |
| question | Text | yes | The user's natural-language question |
| plan | Text | no | The plan (null on fast path) |
| generated_code | Text | no | The exact pandas code that ran (shown in the code panel) |
| result_summary_json | Text (JSON) | no | Bounded result summary (scalars / ≤ `AGENT_RESULT_ROWS` table) — never the full result |
| answer | Text | no | Final plain-language answer |
| status | Text | yes | `running` → `completed` \| `failed` |
| low_confidence | Boolean | yes | True if retries exhausted → best-guess-with-flag; default false |
| retry_count | Integer | yes | How many refine loops ran; default 0 |
| step_trace_json | Text (JSON) | no | `[{step, status, detail, ts}]` — the live trace, persisted |
| chart_spec_json | Text (JSON) | no | **Phase 2** — Vega-Lite v5 spec with bounded inline data (null when not chartable) |
| session_id | Text (FK→sessions.id) | no | **Phase 3** — the session this run belongs to |
| source_ids_json | Text (JSON) | no | **Phase 3** — the selected source ids for this run (one for single-source; several for multi-source join/compare). `dataset_id` remains the primary source for back-compat |
| prompt_tokens | Integer | yes | From Anthropic `usage`; default 0 (displayed in Phase 2) |
| completion_tokens | Integer | yes | From Anthropic `usage`; default 0 |
| cost_usd | Float | yes | Computed from tokens; default 0.0 (displayed in Phase 2) |
| error_message | Text | no | Set when `status = failed` |
| created_at | TIMESTAMP(tz) | yes | Run start |
| updated_at | TIMESTAMP(tz) | yes | Run completion |

> Tokens/cost fields exist in Phase 1 (recorded from the real Anthropic response) even though the UI does not display them until Phase 2 — this avoids a later migration and gives the audit trail cost data from day one.

### Entity: SessionRow (`sessions`) — Phase 3

A persistent workspace. One session owns many datasets, connections, runs, messages, and annotations, and survives restarts/days.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| title | Text | yes | Display title (auto from first question, user-editable) |
| created_at | TIMESTAMP(tz) | yes | Session start |
| updated_at | TIMESTAMP(tz) | yes | Last activity (used for "recent sessions" ordering) |

### Entity: SessionMessageRow (`session_messages`) — Phase 3

The persisted conversation thread — enables multi-turn context and cross-day restore.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| session_id | Text (FK→sessions.id) | yes | Owning session |
| role | Text | yes | `"user"` or `"assistant"` |
| content | Text | yes | The question (user) or the answer prose (assistant) — **privacy-safe text only**, never raw rows |
| run_id | Text (FK→analysis_runs.id) | no | Links an assistant message to its run (code/chart/trace) |
| created_at | TIMESTAMP(tz) | yes | Turn time (ordering) |

> Only prose crosses into `session_messages` — user questions and the agent's own answers. No sample rows, no result tables, no DSN. The last `AGENT_MEMORY_TURNS` (default 8) are loaded into the agent's `conversation`.

### Entity: ConnectionRow (`connections`) — Phase 3

A live SQL DB source. **Holds credentials — see "Sensitive Data".**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (the `source_id` for a DB source) |
| name | Text | yes | User label (e.g. "prod-replica") |
| kind | Text | yes | SQLAlchemy dialect: `"postgresql"` \| `"mysql"` \| `"sqlite"` |
| dsn | Text | yes | The SQLAlchemy connection string **with credentials** — stored only here (git-ignored SQLite), **never** returned in full, logged, or sent to the LLM |
| schema_json | Text (JSON) | no | Cached introspected schema `[{table, columns:[{name,dtype}]}]` (schema only, LLM-visible) |
| sample_rows_json | Text (JSON) | no | Cached `LIMIT AGENT_SAMPLE_ROWS` sample per relevant table, cell-capped (LLM-visible) |
| session_id | Text (FK→sessions.id) | no | Owning session |
| created_at | TIMESTAMP(tz) | yes | Connect time |
| updated_at | TIMESTAMP(tz) | yes | Last touched |

> The API returns a **masked** DSN (`postgresql://user:***@host:5432/db`); the raw `dsn` is write-only from the client's view. Modelled as pydantic `SecretStr` in-memory; `.get_secret_value()` is used only at the SQLAlchemy engine boundary.

### Entity: ColumnAnnotationRow (`column_annotations`) — Phase 3

User-authored business meaning for a column of a source.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| source_id | Text | yes | `DatasetRow.id` or `ConnectionRow.id` the column belongs to |
| table_name | Text | no | Table name for DB sources (null for single-table file sources) |
| column | Text | yes | Column name |
| note | Text | yes | The user's note (privacy-safe text; injected into LLM context) |
| created_at | TIMESTAMP(tz) | yes | Created |
| updated_at | TIMESTAMP(tz) | yes | Last edited |

> Uniqueness: one annotation per `(source_id, table_name, column)`; `PUT` upserts.

### Relationships

- `AnalysisRunRow.dataset_id` → `DatasetRow.id` (many runs per dataset). Phase 3: `AnalysisRunRow.source_ids_json` may reference several sources (files and/or connections).
- Phase 3: `SessionRow` 1→N `DatasetRow`, `ConnectionRow`, `AnalysisRunRow`, `SessionMessageRow`, `ColumnAnnotationRow` (all via `session_id`, except annotations which key on `source_id`).
- `SessionMessageRow.run_id` → `AnalysisRunRow.id` (an assistant turn links to its run).
- `ColumnAnnotationRow.source_id` → `DatasetRow.id` or `ConnectionRow.id`.

## On-disk Uploaded-file Store Layout

```
./data/
  agent.db                     # SQLite (metadata, runs, sessions, connections, annotations)
  uploads/
    <dataset_id>.csv           # raw uploaded file (git-ignored)
    <dataset_id>.xlsx          # Phase 3 — Excel
    <dataset_id>.json          # Phase 3 — JSON
    <dataset_id>.parquet       # Phase 3 — Parquet
    <dataset_id>.pdf           # Phase 3 — PDF
    <dataset_id>.log           # Phase 3 — log/text
```
`src/analysis/store.py` owns this directory: `save(file, filename) -> dataset_id` (extension taken from `source_kind`), `path(dataset_id, kind) -> Path`, `load_df(dataset_id) -> DataFrame` (dispatches to the per-format loader in Phase 3), `profile(dataset_id) -> DatasetMeta`. Only `load_df` reads the full file, and only the executor calls it — the profile (schema + samples) is what everything else uses. **DB sources are not stored on disk** — they live in `ConnectionRow` and are reached over a SQLAlchemy engine (`src/analysis/db_source.py`).

## Data Lifecycle

- **Create:** `DatasetRow` on upload / `ConnectionRow` on connect; `SessionRow` on first activity; `AnalysisRunRow` at ask time (status `running`, finalized to `completed`/`failed`); `SessionMessageRow` in `finalize`; `ColumnAnnotationRow` on annotation upsert.
- **Update:** run row updated in `finalize`/`handle_error`; `SessionRow.updated_at` touched on activity; annotation `PUT` upserts.
- **Delete:** manual in Phase 1. Phase 3 adds session/dataset/connection deletion — removing a dataset deletes its on-disk file; removing a connection drops its `ConnectionRow` (and its DSN); removing a session cascades to its datasets/connections/runs/messages/annotations.
- **Retention:** unbounded (personal audit trail); the user prunes manually per session.

## Sensitive Data

The **raw dataset is the sensitive asset** and never enters the DB or any LLM request — it stays on the local filesystem (file sources) or inside the user's database (DB sources). `schema_json` (column names) and `sample_rows_json` (≤5 bounded rows) are the only data-derived fields persisted and the only data sent to Claude; both are intentionally minimal and cell-length-capped. The Anthropic API key lives only in `.env` (git-ignored), read via `AGENT_` settings.

**Phase 3 — DB connection strings (credentials at rest).** `ConnectionRow.dsn` is the one secret-bearing field the app stores. It lives **only** in the git-ignored SQLite DB (`./data/agent.db`), is modelled as a pydantic `SecretStr` in-memory, and is decrypted-at-use only at the SQLAlchemy engine boundary. It is **never** sent to the LLM (not part of any `LlmContext`), **never** logged (structlog records `connection_id`/`dialect`/`host` only), **never** placed in an exception message, and **never** returned in full by the API — every read returns a masked DSN. See `harness/rules/secret-hygiene.md`. (`./data/` is already git-ignored; confirm before creating.)
