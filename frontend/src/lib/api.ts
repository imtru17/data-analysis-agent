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

export type ExportKind = 'csv' | 'parquet' | 'code' | 'report'

/** Build the download URL for an analysis export (Phase 2). Origin-root path. */
export function exportUrl(runId: string, kind: ExportKind): string {
  return `/analyses/${encodeURIComponent(runId)}/export?kind=${kind}`
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
  options: { want_chart?: boolean } = {},
): Promise<void> {
  const body: Record<string, unknown> = { dataset_id, question }
  if (options.want_chart) body.want_chart = true

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
