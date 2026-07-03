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

**Request:**
```json
{ "dataset_id": "uuid", "question": "What is total revenue by region?" }
```

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
data: {"run_id":"…","status":"completed","answer":"Total revenue is …","generated_code":"result = df.groupby('region')['revenue'].sum()","result_summary":{...},"step_trace":[...],"low_confidence":false,"tokens":{"prompt":0,"completion":0},"cost_usd":0.0}
```
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

## Stubbed / Future Endpoints (not implemented in Phase 1)

Documented so the frontend stubs have a target contract; these return `501 NOT_IMPLEMENTED` (or simply do not exist) in Phase 1:

- **Phase 2:** `POST /analyses` gains `chart_spec` in the `done` payload; `GET /analyses/{id}/export?kind=csv|parquet|code|report`; `GET /cost/today`; `GET /datasets/{id}/profile` (auto-profile + follow-up suggestions).
- **Phase 3:** `POST /sources` (DB connection), `POST /datasets` accepts non-CSV, `GET /sessions`, `POST /sessions/{id}/messages`, `PUT /datasets/{id}/columns/{col}/annotation`, multi-source `POST /analyses` with multiple `dataset_id`s.

## Authentication

None — single local user on `localhost`. No auth, no accounts. (Documented out-of-scope in `spec/roadmap.md`.)
