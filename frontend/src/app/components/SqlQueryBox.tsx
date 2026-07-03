'use client'

import { useState } from 'react'
import { runQuery, ApiError, NetworkError, type QueryResult } from '@/lib/api'

// Phase-4 SQL query box: a monospace textarea + Run button. The dataset's frame
// is registered under the view name `data`, so the placeholder/helper text shows
// `SELECT * FROM data LIMIT 10`. Runs POST /datasets/{id}/query. A bad query is
// caught as a 400 and shown as a friendly INLINE error banner (the server's
// BAD_REQUEST message) — never a stack trace. Run is disabled while in flight.

interface SqlQueryBoxProps {
  datasetId: string
  onResult: (result: QueryResult, sql: string) => void
  onNetworkError?: () => void
}

const PLACEHOLDER = 'SELECT * FROM data LIMIT 10'

export function SqlQueryBox({ datasetId, onResult, onNetworkError }: SqlQueryBoxProps) {
  const [sql, setSql] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canRun = sql.trim().length > 0 && !running

  async function run() {
    if (!canRun) return
    setRunning(true)
    setError(null)
    try {
      const result = await runQuery(datasetId, sql.trim())
      onResult(result, sql.trim())
    } catch (err) {
      if (err instanceof NetworkError) {
        onNetworkError?.()
        setError("Can't reach the server — is it running on :8001?")
      } else if (err instanceof ApiError) {
        // The friendly DuckDB parse/execution message.
        setError(err.message)
      } else {
        setError('Could not run that query.')
      }
    } finally {
      setRunning(false)
    }
  }

  return (
    <div data-testid="sql-query-box">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        Query your data with SQL
      </p>
      <p className="mb-2 text-[11px] text-gray-400">
        Runs locally via DuckDB — the table is named{' '}
        <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[10px] text-gray-700">
          data
        </code>
        . Nothing leaves your machine.
      </p>

      <textarea
        data-testid="sql-input"
        value={sql}
        onChange={e => setSql(e.target.value)}
        placeholder={PLACEHOLDER}
        rows={3}
        spellCheck={false}
        onKeyDown={e => {
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            e.preventDefault()
            void run()
          }
        }}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />

      <div className="mt-2 flex items-center gap-3">
        <button
          type="button"
          data-testid="run-query"
          onClick={() => void run()}
          disabled={!canRun}
          className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? 'Running…' : 'Run'}
        </button>
        <span className="text-[11px] text-gray-400">Cmd/Ctrl + Enter to run</span>
      </div>

      {error && (
        <div
          data-testid="sql-error"
          role="alert"
          className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          <span className="font-semibold">Query error:</span> {error}
        </div>
      )}
    </div>
  )
}
