# API

---

## API Style

REST + **SSE** (Server-Sent Events over an HTTP POST response) for live step streaming. Single local backend, FastAPI on port 8001. All non-stream responses use the skeleton envelope: success `{"data": <payload>, "error": null}` via `ok(...)`; errors raise `api_error(code, message, status)` → `{"detail": {"code", "message"}}`.

## Response Envelope

```json
// success
{ "data": { /* payload */ }, "error": null }
// error (HTTPException detail)
{ "detail": { "code": "BAD_REQUEST", "message": "…" } }
```

## Endpoints / Commands (Phase 1)

### `POST /datasets`

**Purpose:** Upload a CSV, store it locally, profile it (schema + samples + row count), return the profile. No LLM call here.

**Request:** `multipart/form-data` with a `file` field (CSV).

**Response:**
```json
{
  "data": {
    "dataset_id": "uuid",
    "filename": "sales.csv",
    "row_count": 10432,
    "columns": [
      { "name": "region", "dtype": "object" },
      { "name": "revenue", "dtype": "float64" }
    ],
    "sample_rows": [ { "region": "West", "revenue": 1200.5 } ]
  },
  "error": null
}
```
> `sample_rows` is bounded to `AGENT_SAMPLE_ROWS` (default 5) with per-cell length cap — this is exactly what the LLM will later see.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | missing file / not a CSV / unparseable CSV (`BAD_REQUEST`) |
| 413 | file exceeds `AGENT_MAX_UPLOAD_MB` (default 500) (`TOO_LARGE`) |
| 500 | disk/profile failure (`INTERNAL`) |

### `POST /analyses`

**Purpose:** Ask a question about a loaded dataset. Runs the agent and **streams live step events**; the final event carries the answer, generated code, and step trace. Persists an `AnalysisRunRow`.

**Request (Phase 1):**
```json
{ "dataset_id": "uuid", "question": "What is total revenue by region?" }
```
**Request (Phase 2 adds `want_chart`; Phase 3 adds multi-source `source_ids` + `session_id`):**
```json
{
  "session_id": "uuid",
  "dataset_id": "uuid",
  "source_ids": ["dataset-uuid", "connection-uuid"],
  "question": "Compare revenue in the CSV to targets in the DB",
  "want_chart": true
}
```
> `dataset_id` stays the single-source primary (back-compat). `source_ids` (optional) lets one ask span several **files and/or DB connections** — the `select_sources` node auto-picks/joins them. `session_id` (optional) threads the run into a session's conversation; if omitted, a session is created/derived server-side.

**Response:** `Content-Type: text/event-stream`. Event sequence:
```
event: step
data: {"run_id":"…","step":"plan","status":"running","detail":"Planning the analysis"}

event: step
data: {"run_id":"…","step":"generate_code","status":"done","detail":"Wrote pandas code"}

event: step
data: {"run_id":"…","step":"execute_locally","status":"done","detail":"Ran locally on 10432 rows"}

event: step
data: {"run_id":"…","step":"verify","status":"done","detail":"Checks passed"}

event: done
data: {"run_id":"…","status":"completed","answer":"Total revenue is …","generated_code":"result = df.groupby('region')['revenue'].sum()","result_summary":{...},"chart_spec":{...|null},"step_trace":[...],"low_confidence":false,"tokens":{"prompt":123,"completion":45},"cost_usd":0.0021}
```
> `chart_spec` (Phase 2) is a Vega-Lite v5 spec or `null`; `tokens`/`cost_usd` carry real usage from the Anthropic response.
On failure a terminal `event: error` with `data: {"run_id":"…","message":"…"}` is sent instead of `done`.

> Streaming transport: the frontend issues `fetch('/analyses', {method:'POST', body})` and reads `response.body.getReader()`, parsing SSE frames (EventSource cannot POST). Each `step` frame updates the live trace; `done` renders the answer + code panel.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | unknown `dataset_id` or empty `question` (`BAD_REQUEST`) — returned as an SSE `error` event once streaming has begun, or a JSON `api_error` if validation fails before the stream opens |
| 500 | agent/LLM failure surfaced as SSE `error` |

### `GET /analyses/{run_id}`

**Purpose:** Fetch a completed/failed run (audit-trail record).

**Response:**
```json
{
  "data": {
    "run_id": "uuid", "dataset_id": "uuid", "question": "…",
    "generated_code": "result = …", "result_summary": { "...": "..." },
    "answer": "…", "status": "completed", "low_confidence": false,
    "tokens": {"prompt": 0, "completion": 0}, "cost_usd": 0.0,
    "step_trace": [ { "step": "plan", "status": "done", "detail": "…", "ts": "…" } ],
    "created_at": "2026-07-03T10:00:00Z"
  },
  "error": null
}
```
**Error cases:** 404 `NOT_FOUND` if unknown.

### `GET /analyses`

**Purpose:** List recent runs (the history/audit trail), newest first.

**Request:** query `?dataset_id=<uuid>&limit=50` (both optional).

**Response:** `{ "data": [ { "run_id","question","status","created_at","dataset_id" } ], "error": null }`.

### `GET /health`

Unchanged skeleton endpoint — `{ "data": {"status":"ok"}, "error": null }`.

## Phase 2 Endpoints (built)

- `POST /analyses` gains `want_chart` (request) and `chart_spec` (done payload).
- `GET /analyses/{id}/export?kind=csv|parquet|code|report` — download the cleaned/derived dataset, the code, or a shareable report (`src/api/exports.py`).
- `GET /cost/today` — running daily token/cost total (`src/api/cost.py`).
- `GET /datasets/{id}/profile` — rich local profile + 2–3 LLM-suggested follow-up questions (cached).

## Phase 3 Endpoints (final phase)

All use the standard envelope. DB sources never expose the DSN in full (always masked).

### `POST /connections`
**Purpose:** Register a live SQL DB source. Introspects schema + draws a bounded sample; caches both. No dataset file.
**Request:** `{ "name": "prod-replica", "kind": "postgresql|mysql|sqlite", "dsn": "postgresql://user:pw@host:5432/db", "session_id": "uuid?" }`
**Response:** `{ "data": { "connection_id":"uuid", "name":"prod-replica", "kind":"postgresql", "dsn_masked":"postgresql://user:***@host:5432/db", "tables":[{"table":"orders","columns":[{"name":"id","dtype":"integer"}]}] }, "error": null }`
**Rules:** the raw `dsn` is stored only in SQLite and **never** echoed back — the response carries `dsn_masked` only. **Errors:** 400 `BAD_REQUEST` (bad DSN / unreachable / unsupported dialect — message never includes the DSN), 400 on introspection failure.

### `GET /connections`
**Purpose:** List DB connections (masked). **Response:** `{ "data": [ { "connection_id","name","kind","dsn_masked","session_id" } ], "error": null }`.

### `POST /datasets` (non-CSV, Phase 3)
Same endpoint as Phase 1, now accepting `.csv/.xlsx/.json/.parquet/.pdf/.log/.txt`. Detects `source_kind` from the extension, loads via the matching loader, returns the same profile shape. **Errors:** 400 `BAD_REQUEST` with a friendly reason when a format has no clean table (e.g. a PDF with no detectable table); 413 `TOO_LARGE`; 415-style `BAD_REQUEST` for an unsupported extension.

### `GET /sessions`
**Purpose:** List recent sessions (newest first). **Response:** `{ "data": [ { "session_id","title","created_at","updated_at","dataset_count","run_count" } ], "error": null }`.

### `POST /sessions`
**Purpose:** Create a session. **Request:** `{ "title": "Q3 revenue" }` (optional). **Response:** `{ "data": { "session_id","title" }, "error": null }`.

### `GET /sessions/{id}`
**Purpose:** Restore a session across days — its datasets, connections (masked), conversation thread, and annotations.
**Response:** `{ "data": { "session_id","title","datasets":[...],"connections":[...masked...],"messages":[{"role","content","run_id","created_at"}],"annotations":[{"source_id","table_name","column","note"}] }, "error": null }`.
> `messages` restores the thread so a next-day reopen continues the conversation. Message `content` is prose only — never raw rows or a DSN.

### `PUT /datasets/{id}/columns/{col}/annotation`  and  `PUT /connections/{id}/tables/{table}/columns/{col}/annotation`
**Purpose:** Upsert a user note about a column's business meaning (file source / DB source respectively).
**Request:** `{ "note": "amt = net amount in paise" }`. **Response:** `{ "data": { "source_id","table_name","column","note" }, "error": null }`.
**Rules:** one annotation per `(source_id, table_name, column)`; the note flows into the agent's LLM context via the privacy choke point. **Errors:** 404 unknown source/column.

### `POST /analyses` (multi-source, Phase 3)
As documented above — accepts `source_ids` (files and/or connections) + optional `session_id`. Same SSE stream. **Errors:** 400 `BAD_REQUEST` for an unknown/empty source id or empty question.

## Authentication

None — single local user on `localhost`. No auth, no accounts. (Documented out-of-scope in `spec/roadmap.md`.)
