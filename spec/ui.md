# UI

---

## UI Type

Chat interface — a single-page Next.js 15 static export (React 19 + Tailwind 4), served by FastAPI at `http://localhost:8001/app/`. One screen: a chat workspace with an upload control, a message thread, a live step trace, a collapsible code panel, and a rail of clearly-labelled "coming soon" stubs.

## Views / Screens

### Screen: Chat Workspace (`frontend/src/app/page.tsx`)

**Purpose:** upload a CSV, ask questions, watch the agent work live, read answers, inspect the code.

**Layout:**
- **Header bar** — app title, and a greyed **"Today: —"** cost placeholder badge (stub, see below).
- **Left/main column** — the message thread + composer.
- **Right rail** — a "Coming soon" panel listing the roadmap features as disabled cards.

**Key elements (REAL in Phase 1):**
- **Upload control** — a file input / drag-drop accepting `.csv`. On upload → `POST /datasets`; on success a system message shows the **profile**: filename, row count, and a compact schema table (column → dtype) plus a "5 sample rows" preview. This is the one dataset in context.
- **Message thread** — alternating user questions and agent answers. Each agent answer shows the plain-language text with key numbers highlighted.
- **Composer** — a text box + Send. Sends `POST /analyses` with `{dataset_id, question}` and opens the SSE stream. Disabled until a dataset is loaded (with a hint: "Upload a CSV to start").
- **Live step trace** — while an answer is in flight, an inline row of step chips animates in order: `Planning → Writing code → Running locally → Verifying → Answering`. Each chip flips from running (spinner) to done (check) as `step` SSE events arrive. On the fast path the "Planning" chip is shown as skipped.
- **Collapsible code panel** — under each answer, a "Show code ▸" disclosure reveals the exact pandas snippet the agent ran (monospace, copy button). Collapsed by default.
- **Answer meta** — a small caption; in Phase 1 it shows a greyed "tokens/cost —" placeholder (stub).

**Actions available:** upload a CSV; type + send a question; expand/collapse the code panel; copy the code.

### Phase 2 surfaces (built — replaced the Phase-1 stubs)

Charts (zoomable + PNG/SVG download), Exports/Report menu, per-answer token/cost badge + header "Today: $x" total, and the auto-profile card + clickable follow-up chips are all **real** since Phase 2.

### Phase 3 surfaces (final phase — these REPLACE the remaining Phase-1 stubs)

By end of Phase 3 **no Phase-1 stub remains**; every "Coming soon" card becomes a working surface. The right-rail "Coming soon" panel is retired.

| Surface | Where | Behaviour |
|---------|-------|-----------|
| **Connect DB dialog** (`ConnectDb.tsx`) | "Connect database" in the source area opens a modal: name, dialect (Postgres/MySQL/SQLite), connection string | `POST /connections`; on success shows the source with its introspected tables. The DSN field is write-only — the UI never displays the entered credentials back; the source chip shows the **masked** DSN. |
| **Non-CSV upload** (extends upload control) | Upload accepts `.csv/.xlsx/.json/.parquet/.pdf/.log/.txt` | `POST /datasets`; helper text now reads "CSV · Excel · JSON · Parquet · PDF · logs". A format with no clean table shows the friendly server reason inline (not a crash). |
| **Multi-source panel + source picker** (`SourcePanel.tsx`) | A panel listing loaded sources (files + connections); the composer gains a source picker (multi-select) | Selected `source_ids` are sent with `POST /analyses`. Default: all in-session sources are candidates and `select_sources` auto-picks; the user may pin specific ones. |
| **Session / history browser** (`SessionBrowser.tsx`) | "History" in the header opens a real panel of recent sessions | `GET /sessions`; clicking a session calls `GET /sessions/{id}` and restores its datasets, connections, conversation thread, and annotations — across days. |
| **Annotation editor** (`AnnotationEditor.tsx`) | Inline "✎" on any column in the schema/profile table (file or DB source/table) | `PUT .../annotation`; the saved note shows under the column and is used by the agent on the next ask. |

**Multi-turn thread:** the message thread is now a persistent conversation — follow-ups ("and by month?") resolve against prior turns, and reopening a session restores the full thread with each answer's code/chart/trace.

**Anything still a stub:** nothing from the Phase-1 vision. (No auth/multi-user by design — that is out-of-scope in `spec/roadmap.md`, not a stub.)

## Error States

- **Upload rejected** (unsupported type / too large / unparseable / no table in a PDF) → an inline system message in the thread with the friendly server reason (e.g. "Couldn't find a table in that PDF — try CSV/Excel/Parquet."). Phase 3 accepts CSV/Excel/JSON/Parquet/PDF/logs up to the size limit.
- **DB connect failed** (Phase 3) → the Connect dialog shows the server reason (unreachable / bad DSN / unsupported dialect) — **the message never echoes the connection string**.
- **No dataset yet** → composer disabled with the "Upload a CSV to start" hint.
- **Analysis in flight** → step chips animate; composer disabled until `done`/`error`.
- **Agent error** (SSE `error` event) → the in-flight step chip turns red and an agent message shows the message + a "Try rephrasing" hint. The failed run is still in history.
- **Low-confidence answer** → the answer is shown with a subtle "⚠ best guess" badge and the agent's note on what it tried (from `low_confidence`).
- **Network error** → toast "Can't reach the server — is it running on :8001?".

## E2E Tests

`frontend/tests/e2e/analysis.spec.ts` (Playwright, required Phase-1 deliverable): drives the built app against a running server — uploads a small CSV, sends a question, asserts the step chips appear, asserts a non-empty answer renders, and asserts the code panel reveals code. Config in `frontend/playwright.config.ts`. This is part of the Phase-1 gate (not an HTTP-200 check).

`frontend/tests/e2e/insight.spec.ts` (Phase 2): profile card + follow-up chips, chart render + download, cost badge/today total, export menu.

`frontend/tests/e2e/sources.spec.ts` (Phase 3, required): connects a **local SQLite** DB source (a seeded file, no external credentials), asks a question that pushes SQL down and returns an answer; uploads a non-CSV (Parquet or Excel) and asks; runs a multi-source compare across the file + the DB; adds a column annotation and confirms it persists; reopens a session from the history browser and asserts the prior thread is restored. Part of the Phase-3 gate.

## Tech Stack

Next.js 15 static export (`output: 'export'`, `basePath: '/app'`) + React 19 + Tailwind 4. SSE consumed via `fetch` + `ReadableStream` reader in `frontend/src/lib/api.ts` (EventSource can't POST). Components under `frontend/src/app/components/`.
