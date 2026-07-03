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

### Labelled NON-FUNCTIONAL Stubs (Phase 1)

Every future feature is visible but unmistakably inert, so it reads as "coming soon", never as a bug. Marking convention (applied to all): reduced opacity (`opacity-60`), a small **"Soon"** pill badge, `cursor-not-allowed`, `aria-disabled`, and a tooltip **"Coming soon — arrives in a later phase."** Clicking does nothing (no request, no error).

| Stub | Where | Marked as |
|------|-------|-----------|
| **Charts** | A "📊 Chart" toggle on the composer / an empty "Charts appear here (soon)" card under answers | disabled toggle + Soon pill |
| **Exports / Report** | An "Export ▾" menu in the answer toolbar (CSV, Parquet, Code, Report items) | disabled menu, Soon pill |
| **Connect DB** | "Connect database" button in the right rail | disabled card, Soon pill |
| **Add source / multi-source** | "+ Add source" button near the upload control | disabled, Soon pill |
| **Auto-profile insights + follow-ups** | "Suggested questions (soon)" placeholder chips under the profile message | greyed non-clickable chips |
| **Cost / token + daily total** | Header "Today: —" badge + per-answer "tokens/cost —" caption | greyed placeholder text |
| **Sessions / history browser** | "History" button in the header opening a disabled panel "Your past sessions (soon)" | disabled, Soon pill |
| **Non-CSV upload** | Upload control shows accepted types "CSV now · Excel/JSON/Parquet/PDF/logs soon" | helper text, non-CSV rejected with a friendly message |

The right-rail "Coming soon" panel restates these so the user sees the full vision at a glance.

## Error States

- **Upload rejected** (non-CSV / too large / unparseable) → an inline system message in the thread: "Couldn't read that file: <reason>. Phase 1 supports CSV up to 500 MB." (not a stub — a real, friendly validation message).
- **No dataset yet** → composer disabled with the "Upload a CSV to start" hint.
- **Analysis in flight** → step chips animate; composer disabled until `done`/`error`.
- **Agent error** (SSE `error` event) → the in-flight step chip turns red and an agent message shows the message + a "Try rephrasing" hint. The failed run is still in history.
- **Low-confidence answer** → the answer is shown with a subtle "⚠ best guess" badge and the agent's note on what it tried (from `low_confidence`).
- **Network error** → toast "Can't reach the server — is it running on :8001?".

## E2E Tests

`frontend/tests/e2e/analysis.spec.ts` (Playwright, required Phase-1 deliverable): drives the built app against a running server — uploads a small CSV, sends a question, asserts the step chips appear, asserts a non-empty answer renders, and asserts the code panel reveals code. Config in `frontend/playwright.config.ts`. This is part of the Phase-1 gate (not an HTTP-200 check).

## Tech Stack

Next.js 15 static export (`output: 'export'`, `basePath: '/app'`) + React 19 + Tailwind 4. SSE consumed via `fetch` + `ReadableStream` reader in `frontend/src/lib/api.ts` (EventSource can't POST). Components under `frontend/src/app/components/`.
