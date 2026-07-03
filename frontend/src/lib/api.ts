// Typed client for the local Data Analysis Agent backend.
//
// The app is served under basePath `/app`, but the API routes (`/datasets`,
// `/analyses`, `/health`) live at the ORIGIN ROOT — not under `/app`. Using
// absolute-from-origin paths (`/datasets`) bypasses Next's basePath rewriting,
// so these fetches correctly hit the FastAPI server on the same origin.

export interface Column {
  name: string
  dtype: string
}

// Phase-2 richer per-column profile. All statistical fields are optional so the
// UI degrades gracefully if the backend omits any of them for a given column.
export interface ColumnProfile extends Column {
  null_count?: number
  distinct?: number
  min?: number | string | null
  max?: number | string | null
  mean?: number | null
  top?: unknown
}

export interface DatasetProfile {
  dataset_id: string
  filename: string
  row_count: number
  columns: ColumnProfile[]
  sample_rows: Record<string, unknown>[]
  /** Phase-2 auto-suggested follow-up questions (may be empty). */
  followups?: string[]
}

/** Response shape of GET /datasets/{id}/profile (Phase 2). */
export interface RichProfile {
  profile: {
    row_count: number
    columns: ColumnProfile[]
  }
  followups: string[]
}

/** Response shape of GET /cost/today (Phase 2). */
export interface TodayCost {
  date: string
  cost_usd: number
  prompt_tokens: number
  completion_tokens: number
  run_count: number
}

/** A Vega-Lite v5 JSON spec (or null when the answer has no chart). */
export type ChartSpec = Record<string, unknown>

export type StepStatus = 'running' | 'done'

export interface StepEvent {
  run_id: string
  step: string
  status: StepStatus
  detail?: string
}

export interface Tokens {
  prompt: number
  completion: number
}

export interface DoneEvent {
  run_id: string
  status: string
  answer: string
  generated_code: string
  result_summary?: Record<string, unknown>
  step_trace?: unknown[]
  low_confidence?: boolean
  low_confidence_note?: string
  tokens?: Tokens
  cost_usd?: number
  /** Phase-2: a Vega-Lite spec to render below the answer, or null. */
  chart_spec?: ChartSpec | null
}

export interface StreamErrorEvent {
  run_id?: string
  message: string
}

export interface StreamHandlers {
  onStep: (event: StepEvent) => void
  onDone: (event: DoneEvent) => void
  onError: (event: StreamErrorEvent) => void
}

/** Raised when the server cannot be reached at all (network / connection error). */
export class NetworkError extends Error {
  constructor(message = "Can't reach the server — is it running on :8001?") {
    super(message)
    this.name = 'NetworkError'
  }
}

/** Raised when the server responds with a non-2xx status carrying an error envelope. */
export class ApiError extends Error {
  status: number
  code: string
  constructor(message: string, status: number, code = 'ERROR') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

interface ErrorEnvelope {
  detail?: { code?: string; message?: string }
}

async function parseErrorEnvelope(res: Response): Promise<ApiError> {
  let code = 'ERROR'
  let message = `Request failed (${res.status})`
  try {
    const body = (await res.json()) as ErrorEnvelope
    if (body?.detail?.message) message = body.detail.message
    if (body?.detail?.code) code = body.detail.code
  } catch {
    // non-JSON error body — keep the default message
  }
  return new ApiError(message, res.status, code)
}

/**
 * Upload a CSV file and receive its profile (schema + samples + row count).
 * POST /datasets (multipart/form-data, field name `file`).
 */
export async function uploadDataset(file: File): Promise<DatasetProfile> {
  const form = new FormData()
  form.append('file', file)

  let res: Response
  try {
    res = await fetch('/datasets', { method: 'POST', body: form })
  } catch {
    throw new NetworkError()
  }

  if (!res.ok) {
    throw await parseErrorEnvelope(res)
  }

  const body = (await res.json()) as { data: DatasetProfile; error: null }
  return body.data
}

/**
 * Fetch the richer auto-profile + follow-up suggestions for a dataset.
 * GET /datasets/{id}/profile (Phase 2). Returns null on any failure so an upload
 * still succeeds even if the profile endpoint is unavailable.
 */
export async function fetchProfile(datasetId: string): Promise<RichProfile | null> {
  try {
    const res = await fetch(`/datasets/${datasetId}/profile`)
    if (!res.ok) return null
    const body = (await res.json()) as { data: RichProfile; error: null }
    return body.data ?? null
  } catch {
    return null
  }
}

/**
 * Fetch today's running token/cost total. GET /cost/today (Phase 2).
 * Returns null on failure so the header simply shows $0.00 rather than erroring.
 */
export async function fetchTodayCost(): Promise<TodayCost | null> {
  try {
    const res = await fetch('/cost/today')
    if (!res.ok) return null
    const body = (await res.json()) as { data: TodayCost; error: null }
    return body.data ?? null
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Phase 3: DB connections, sessions, annotations, multi-source.
// ---------------------------------------------------------------------------

/** A live SQL DB source. The raw DSN is NEVER returned — only `dsn_masked`. */
export interface Connection {
  connection_id: string
  name: string
  kind: string
  dsn_masked: string
  session_id?: string
  tables?: { table: string; columns: Column[] }[]
}

/** Kinds a loaded source can take in the unified source panel. */
export type SourceKind = 'file' | 'db'

/** A unified loaded source (an uploaded file OR a DB connection). */
export interface Source {
  id: string
  kind: SourceKind
  name: string
  /** A short secondary line: "10,432 rows · 4 cols" or the masked DSN. */
  detail?: string
}

export interface SessionSummary {
  session_id: string
  title?: string
  created_at?: string
  updated_at?: string
  dataset_count?: number
  run_count?: number
}

export interface SessionMessage {
  role: string
  content: string
  run_id?: string
  created_at?: string
}

export interface SessionAnnotation {
  source_id: string
  table_name?: string | null
  column: string
  note: string
}

export interface SessionDetail {
  session_id: string
  title?: string
  datasets?: DatasetProfile[]
  connections?: Connection[]
  messages?: SessionMessage[]
  annotations?: SessionAnnotation[]
}

/** Register a live SQL DB source. POST /connections. The raw DSN is write-only. */
export async function createConnection(input: {
  name: string
  kind: string
  dsn: string
  session_id?: string
}): Promise<Connection> {
  let res: Response
  try {
    res = await fetch('/connections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: Connection; error: null }
  return body.data
}

/** List registered DB connections (masked). GET /connections. */
export async function fetchConnections(): Promise<Connection[]> {
  try {
    const res = await fetch('/connections')
    if (!res.ok) return []
    const body = (await res.json()) as { data: Connection[]; error: null }
    return body.data ?? []
  } catch {
    return []
  }
}

/** List recent sessions (newest first). GET /sessions. */
export async function fetchSessions(): Promise<SessionSummary[]> {
  try {
    const res = await fetch('/sessions')
    if (!res.ok) return []
    const body = (await res.json()) as { data: SessionSummary[]; error: null }
    return body.data ?? []
  } catch {
    return []
  }
}

/** Create a session. POST /sessions. */
export async function createSession(title?: string): Promise<SessionSummary> {
  let res: Response
  try {
    res = await fetch('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(title ? { title } : {}),
    })
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: SessionSummary; error: null }
  return body.data
}

/** Restore a session — its datasets, connections, thread, and annotations. */
export async function fetchSession(sessionId: string): Promise<SessionDetail | null> {
  try {
    const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}`)
    if (!res.ok) return null
    const body = (await res.json()) as { data: SessionDetail; error: null }
    return body.data ?? null
  } catch {
    return null
  }
}

/** Fetch a completed run (used to restore code/trace for a session thread). */
export async function fetchRun(runId: string): Promise<DoneEvent | null> {
  try {
    const res = await fetch(`/analyses/${encodeURIComponent(runId)}`)
    if (!res.ok) return null
    const body = (await res.json()) as { data: DoneEvent; error: null }
    return body.data ?? null
  } catch {
    return null
  }
}

/** Upsert a column annotation for a FILE dataset source. */
export async function saveDatasetAnnotation(
  datasetId: string,
  column: string,
  note: string,
): Promise<SessionAnnotation> {
  let res: Response
  try {
    res = await fetch(
      `/datasets/${encodeURIComponent(datasetId)}/columns/${encodeURIComponent(column)}/annotation`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      },
    )
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: SessionAnnotation; error: null }
  return body.data
}

/** Upsert a column annotation for a DB connection table column. */
export async function saveConnectionAnnotation(
  connectionId: string,
  table: string,
  column: string,
  note: string,
): Promise<SessionAnnotation> {
  let res: Response
  try {
    res = await fetch(
      `/connections/${encodeURIComponent(connectionId)}/tables/${encodeURIComponent(
        table,
      )}/columns/${encodeURIComponent(column)}/annotation`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      },
    )
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: SessionAnnotation; error: null }
  return body.data
}

export type ExportKind = 'csv' | 'parquet' | 'code' | 'report'

/** Build the download URL for an analysis export (Phase 2). Origin-root path. */
export function exportUrl(runId: string, kind: ExportKind): string {
  return `/analyses/${encodeURIComponent(runId)}/export?kind=${kind}`
}

// ---------------------------------------------------------------------------
// Phase 4: Data workbench (LOCAL, no LLM) — profile tiles, column drill-in,
// DuckDB SQL query + result table + full-result CSV download.
// ---------------------------------------------------------------------------

/** A detected foreign-key reference from one dataset column to another's PK column. */
export interface FkCandidate {
  references_dataset_id: string
  references_dataset_name: string
  references_column: string
}

/** One column's tile payload: distinct/null counts + PK/FK detection. */
export interface TileColumn {
  name: string
  dtype: string
  distinct: number
  null_count: number
  is_pk_candidate: boolean
  fk_candidates: FkCandidate[]
}

/** Response shape of GET /datasets/{id}/tiles. */
export interface DatasetTiles {
  row_count: number
  columns: TileColumn[]
  primary_key_candidates: string[]
  foreign_key_candidates: {
    column: string
    references_dataset_id: string
    references_dataset_name: string
    references_column: string
  }[]
}

/** One (value, count) pair in a column drill-in. */
export interface ColumnValue {
  value: unknown
  count: number
}

/** Response shape of GET /datasets/{id}/columns/{col}/values. */
export interface ColumnValues {
  column: string
  total: number
  values: ColumnValue[]
  truncated: boolean
}

/** Response shape of POST /datasets/{id}/query. */
export interface QueryResult {
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  truncated: boolean
}

/** Fetch the profile-tiles payload for a dataset. GET /datasets/{id}/tiles. */
export async function fetchTiles(datasetId: string): Promise<DatasetTiles> {
  let res: Response
  try {
    res = await fetch(`/datasets/${encodeURIComponent(datasetId)}/tiles`)
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: DatasetTiles; error: null }
  return body.data
}

/** Fetch a column's top values + counts (drill-in). GET /datasets/{id}/columns/{col}/values. */
export async function fetchColumnValues(datasetId: string, col: string): Promise<ColumnValues> {
  let res: Response
  try {
    res = await fetch(
      `/datasets/${encodeURIComponent(datasetId)}/columns/${encodeURIComponent(col)}/values`,
    )
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: ColumnValues; error: null }
  return body.data
}

/** Run raw SQL locally via DuckDB over the dataset. POST /datasets/{id}/query. */
export async function runQuery(datasetId: string, sql: string): Promise<QueryResult> {
  let res: Response
  try {
    res = await fetch(`/datasets/${encodeURIComponent(datasetId)}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql }),
    })
  } catch {
    throw new NetworkError()
  }
  // A bad query comes back as a 400 BAD_REQUEST carrying the friendly DuckDB
  // message — surfaced as an ApiError the query box renders inline.
  if (!res.ok) throw await parseErrorEnvelope(res)
  const body = (await res.json()) as { data: QueryResult; error: null }
  return body.data
}

/**
 * Re-run the SQL and download the FULL (uncapped) result as a CSV attachment.
 * POST /datasets/{id}/query/download. Reads the blob and triggers a browser
 * download, honouring the server's Content-Disposition filename when present
 * (mirrors the Chart component's anchor-click download idiom).
 */
export async function downloadQueryCsv(datasetId: string, sql: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`/datasets/${encodeURIComponent(datasetId)}/query/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql }),
    })
  } catch {
    throw new NetworkError()
  }
  if (!res.ok) throw await parseErrorEnvelope(res)

  const disposition = res.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  const filename = match?.[1] ?? `query_${datasetId.slice(0, 8)}.csv`

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

interface SseFrame {
  event: string
  data: string
}

/**
 * Parse a buffer of SSE text into complete frames, returning the parsed frames
 * plus any trailing partial frame text that must be carried into the next chunk.
 * Frames are separated by a blank line (\n\n); we normalise CRLF to LF.
 */
function drainFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  const normalised = buffer.replace(/\r\n/g, '\n')
  const parts = normalised.split('\n\n')
  const rest = parts.pop() ?? ''
  const frames: SseFrame[] = []

  for (const raw of parts) {
    const block = raw.trim()
    if (!block) continue
    let event = 'message'
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        event = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trim())
      }
    }
    frames.push({ event, data: dataLines.join('\n') })
  }

  return { frames, rest }
}

function dispatchFrame(frame: SseFrame, handlers: StreamHandlers): void {
  if (!frame.data) return
  let payload: unknown
  try {
    payload = JSON.parse(frame.data)
  } catch {
    return
  }
  if (frame.event === 'step') {
    handlers.onStep(payload as StepEvent)
  } else if (frame.event === 'done') {
    handlers.onDone(payload as DoneEvent)
  } else if (frame.event === 'error') {
    handlers.onError(payload as StreamErrorEvent)
  }
}

/**
 * Ask a question about a loaded dataset and stream the live step trace.
 *
 * POST /analyses with a JSON body; the response is `text/event-stream`. Because
 * EventSource cannot issue a POST, we read `response.body.getReader()` and parse
 * SSE frames manually, tolerating partial frames split across network chunks.
 */
export async function streamAnalysis(
  dataset_id: string,
  question: string,
  handlers: StreamHandlers,
  options: { want_chart?: boolean; source_ids?: string[]; session_id?: string } = {},
): Promise<void> {
  const body: Record<string, unknown> = { dataset_id, question }
  if (options.want_chart) body.want_chart = true
  if (options.source_ids && options.source_ids.length > 0) body.source_ids = options.source_ids
  if (options.session_id) body.session_id = options.session_id

  let res: Response
  try {
    res = await fetch('/analyses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new NetworkError()
  }

  // Validation that fails before the stream opens comes back as a JSON api_error.
  if (!res.ok) {
    throw await parseErrorEnvelope(res)
  }

  if (!res.body) {
    throw new NetworkError('The server returned an empty stream.')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch {
      throw new NetworkError('The connection dropped mid-stream.')
    }
    const { value, done } = chunk
    if (value) {
      buffer += decoder.decode(value, { stream: true })
      const { frames, rest } = drainFrames(buffer)
      buffer = rest
      for (const frame of frames) dispatchFrame(frame, handlers)
    }
    if (done) break
  }

  // Flush any trailing frame that arrived without a closing blank line.
  buffer += decoder.decode()
  const { frames } = drainFrames(buffer + '\n\n')
  for (const frame of frames) dispatchFrame(frame, handlers)
}
