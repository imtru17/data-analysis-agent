'use client'

import { useEffect, useState } from 'react'
import { createConnection, ApiError, NetworkError, type Connection } from '@/lib/api'

// Real Phase-3 "Connect database" modal (replaces the Phase-1 stub). The user
// picks a dialect (SQLite / Postgres / MySQL), gives the source a name, and
// enters a connection string (for SQLite, a local file path). On submit it calls
// POST /connections. The DSN field is WRITE-ONLY: the UI never echoes the entered
// credentials back — the connected source shows only the server's masked DSN, and
// a connect error surfaces the server reason (which never includes the DSN).

interface ConnectDbProps {
  open: boolean
  onClose: () => void
  onConnected: (connection: Connection) => void
  onNetworkError: () => void
  sessionId?: string | null
}

const KINDS: { value: string; label: string; hint: string }[] = [
  { value: 'sqlite', label: 'SQLite', hint: 'e.g. /path/to/analytics.db' },
  { value: 'postgresql', label: 'Postgres', hint: 'postgresql://user:pw@host:5432/db' },
  { value: 'mysql', label: 'MySQL', hint: 'mysql://user:pw@host:3306/db' },
]

export function ConnectDb({ open, onClose, onConnected, onNetworkError, sessionId }: ConnectDbProps) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState('sqlite')
  const [dsn, setDsn] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the form each time the dialog opens.
  useEffect(() => {
    if (open) {
      setName('')
      setKind('sqlite')
      setDsn('')
      setError(null)
      setBusy(false)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const kindHint = KINDS.find(k => k.value === kind)?.hint ?? ''
  const canSubmit = dsn.trim().length > 0 && !busy

  async function submit() {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    try {
      const conn = await createConnection({
        name: name.trim() || 'DB source',
        kind,
        dsn: dsn.trim(),
        session_id: sessionId ?? undefined,
      })
      onConnected(conn)
      onClose()
    } catch (err) {
      if (err instanceof NetworkError) {
        onNetworkError()
      } else if (err instanceof ApiError) {
        // The server message never echoes the DSN.
        setError(err.message)
      } else {
        setError('Could not connect to that database.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onMouseDown={e => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Connect a database"
        data-testid="connect-db-dialog"
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Connect a database</h2>
          <button
            type="button"
            aria-label="Close"
            data-testid="connect-db-close"
            onClick={onClose}
            className="rounded px-1.5 text-gray-400 hover:text-gray-700"
          >
            ✕
          </button>
        </div>

        <p className="mb-3 text-xs text-gray-500">
          Only the schema and a small sample are ever sent to the LLM — the connection runs
          read-only and locally. Credentials are stored on your machine and never shown back.
        </p>

        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-medium text-gray-600">Name</span>
          <input
            type="text"
            data-testid="connect-db-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="prod-replica"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </label>

        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-medium text-gray-600">Dialect</span>
          <select
            data-testid="connect-db-kind"
            value={kind}
            onChange={e => setKind(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {KINDS.map(k => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>

        <label className="mb-1 block">
          <span className="mb-1 block text-xs font-medium text-gray-600">
            {kind === 'sqlite' ? 'Database file path' : 'Connection string'}
          </span>
          <input
            type="text"
            data-testid="connect-db-dsn"
            value={dsn}
            onChange={e => setDsn(e.target.value)}
            placeholder={kindHint}
            spellCheck={false}
            autoComplete="off"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </label>
        <p className="mb-3 text-[11px] text-gray-400">{kindHint}</p>

        {error && (
          <div
            data-testid="connect-db-error"
            className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
          >
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="connect-db-submit"
            onClick={() => void submit()}
            disabled={!canSubmit}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Connecting…' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  )
}
