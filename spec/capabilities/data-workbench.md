# Capability: Data Workbench — Profile Tiles + SQL Query Box

## What It Does
Gives the user a hands-on, **entirely local** (no LLM call) workbench on a loaded dataset: clickable profile tiles (row count, per-column distinct + null counts, detected primary-key and foreign-key candidates) with a per-column value-counts drill-in, plus a SQL query box that runs raw SQL locally via DuckDB over the dataset's DataFrame and returns a downloadable result table.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id | uuid | path (`GET /datasets/{id}/tiles`, `.../query`, `.../query/download`) | yes |
| col | string (column name) | path (`GET /datasets/{id}/columns/{col}/values`) | yes |
| sql | string | `POST /datasets/{id}/query` and `.../query/download` body | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| tiles | JSON `{ row_count, columns:[{name,dtype,distinct,null_count,is_pk_candidate,fk_candidates:[...]}], primary_key_candidates:[...], foreign_key_candidates:[...] }` | `GET /datasets/{id}/tiles` response → profile-tiles grid |
| column values | JSON `{ column, total, values:[{value,count}], truncated }` | `GET /datasets/{id}/columns/{col}/values` response → drill-in |
| query result | JSON `{ columns, rows, row_count, truncated }` | `POST /datasets/{id}/query` response → result table |
| result CSV | `text/csv` attachment (full result) | `POST /datasets/{id}/query/download` response → file download |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local dataset store (`store.load_df`) | Read the FULL DataFrame locally (the only full-file read path) | Missing/unreadable file → `NOT_FOUND`/`BAD_REQUEST` |
| DuckDB (in-process) | Register the DataFrame as an in-memory view, run the user's `SELECT` locally, fetch results | Bad SQL → caught → friendly `BAD_REQUEST` (never a 500 stack trace) |
| Other `DatasetRow`s (local) | Load PK-candidate columns of other loaded datasets to test FK subset membership | Any load error on a candidate is skipped silently — FK detection is best-effort, never fatal |

> No Anthropic / network call anywhere in this capability. DuckDB queries the in-memory pandas frame in-process — the privacy invariant holds trivially because nothing leaves the machine and no prompt is built.

## Business Rules
- **Local-only, no LLM, no network.** Tiles are deterministic local pandas (reusing `analysis.profile.compute_profile` for `row_count`/`distinct`/`null_count`); SQL runs in-process via DuckDB over the DataFrame. This preserves the privacy invariant by construction.
- **PK-candidate:** a column whose non-null value count equals its distinct count **and** whose `null_count == 0` (i.e. unique + non-null over the full data).
- **FK-candidate:** a column whose set of non-null distinct values is a **subset** of another loaded dataset's PK-candidate column's value set. A `<name>_id` / `<parent>` name heuristic is an additional signal (and orders candidates) but the subset test is the core requirement. A cheap distinct-count guard short-circuits columns that cannot be a subset.
- **FK reference scope:** other datasets in the **same session** when the dataset has a `session_id`; otherwise the most recent `AGENT_WORKBENCH_FK_SCAN` datasets (default 25). Bounded so detection stays fast for a single local user. > **Assumed:** same-session-else-recent-25 is the FK scan scope (not "all datasets ever") — keeps detection fast and relevant; flagged for confirmation.
- **SQL table names:** the DataFrame is registered under the canonical view name **`data`** *and* the sanitized filename stem (e.g. `orders.csv` → `orders`), both documented in the UI so a query can `SELECT ... FROM data`.
- **Read-only in spirit / bounded display:** the query result table is capped to `AGENT_WORKBENCH_DISPLAY_ROWS` (default 500) rows with `truncated: true` when the full result is larger; the **download** re-runs the same SQL and returns the **full** result as CSV (a local file for the local user, reusing the `export.py` `Content-Disposition` pattern).
- **Graceful errors:** any DuckDB parse/execution error is caught and returned as a friendly `BAD_REQUEST` with the DuckDB message — the user never sees a 500 or a stack trace.
- **No new tables/migration:** this capability is read-only over existing `DatasetRow`s + on-disk files; no schema change.

## Success Criteria
- [ ] `GET /datasets/{id}/tiles` returns `row_count` and per-column `distinct`/`null_count` equal to the **full-data** pandas values (fixture has more rows than `AGENT_SAMPLE_ROWS`, so a sampled answer would differ).
- [ ] A unique, non-null column is flagged `is_pk_candidate: true`; a column with duplicates or nulls is not.
- [ ] Given a parent dataset with a unique `id` and a child dataset with a `<parent>_id` column whose values are a subset of the parent's `id`, the child column is returned as an FK candidate referencing `{references_dataset_id, references_dataset_name, references_column}`.
- [ ] Clicking a column tile (`GET /datasets/{id}/columns/{col}/values`) returns that column's top values + counts computed over the full data.
- [ ] `POST /datasets/{id}/query` with a valid grouped `SELECT ... FROM data` returns correct `columns`/`rows`/`row_count`; an over-cap result sets `truncated: true`.
- [ ] A malformed SQL string returns HTTP 400 `BAD_REQUEST` with a friendly message and **no** 500 / stack trace.
- [ ] `POST /datasets/{id}/query/download` returns a `text/csv` attachment containing the **full** result (row count matching the unbounded query), with a `Content-Disposition` filename.
