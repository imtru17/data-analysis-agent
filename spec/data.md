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
| source_kind | Text | yes | `"csv"` in Phase 1 (`excel`/`json`/`parquet`/`pdf`/`log`/`db` later); default `"csv"` |
| file_path | Text | yes | Relative path under `./data/uploads/` (never the contents) |
| row_count | Integer | yes | Total rows in the full file |
| schema_json | Text (JSON) | yes | Ordered `[{name, dtype}]` — column names + dtypes |
| sample_rows_json | Text (JSON) | yes | ≤ `AGENT_SAMPLE_ROWS` sample rows, cell-length capped (the LLM-visible sample) |
| session_id | Text | no | Null in Phase 1; links to a session in Phase 3 |
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
| prompt_tokens | Integer | yes | From Anthropic `usage`; default 0 (displayed in Phase 2) |
| completion_tokens | Integer | yes | From Anthropic `usage`; default 0 |
| cost_usd | Float | yes | Computed from tokens; default 0.0 (displayed in Phase 2) |
| error_message | Text | no | Set when `status = failed` |
| created_at | TIMESTAMP(tz) | yes | Run start |
| updated_at | TIMESTAMP(tz) | yes | Run completion |

> Tokens/cost fields exist in Phase 1 (recorded from the real Anthropic response) even though the UI does not display them until Phase 2 — this avoids a later migration and gives the audit trail cost data from day one.

### Relationships

- `AnalysisRunRow.dataset_id` → `DatasetRow.id` (many runs per dataset).
- Phase 3: `DatasetRow.session_id` and a new `SessionRow` (one session → many datasets, many runs, many annotations); `ColumnAnnotationRow` (dataset_id + column → note). Not created in Phase 1.

## On-disk Uploaded-file Store Layout

```
./data/
  agent.db                     # SQLite
  uploads/
    <dataset_id>.csv           # raw uploaded file (git-ignored)
    <dataset_id>.parquet       # (Phase 3, other formats)
```
`src/analysis/store.py` owns this directory: `save(file) -> dataset_id`, `path(dataset_id) -> Path`, `load_df(dataset_id) -> DataFrame`, `profile(dataset_id) -> DatasetMeta`. Only `load_df` reads the full file, and only the executor calls it — the profile (schema + samples) is what everything else uses.

## Data Lifecycle

- **Create:** `DatasetRow` on upload; `AnalysisRunRow` at ask time (status `running`, finalized to `completed`/`failed`).
- **Update:** run row updated in `finalize`/`handle_error`.
- **Delete:** manual in Phase 1 (delete the DB/uploads). Phase 3 adds session/dataset deletion which removes the row + the on-disk file.
- **Retention:** unbounded in Phase 1 (personal audit trail); the user prunes manually.

## Sensitive Data

The **raw dataset is the sensitive asset** and never enters the DB or any LLM request — it stays on the local filesystem. `schema_json` (column names) and `sample_rows_json` (≤5 bounded rows) are the only data-derived fields persisted and the only data sent to Claude; both are intentionally minimal and cell-length-capped. No auth secrets are stored (single local user); the Anthropic API key lives only in `.env` (git-ignored), read via `AGENT_` settings.
