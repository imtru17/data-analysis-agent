'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  fetchSessions,
  createSession,
  fetchSession,
  NetworkError,
  type SessionSummary,
  type SessionDetail,
} from '@/lib/api'

// Real Phase-3 session / history browser (replaces the Phase-1 stub). Opens from
// the header. Lists recent sessions (GET /sessions), lets the user start a new
// one (POST /sessions), and open a prior one (GET /sessions/{id}) to restore its
// datasets, connections, conversation thread, and annotations — across days.

interface SessionBrowserProps {
  open: boolean
  onClose: () => void
  currentSessionId: string | null
  onRestore: (detail: SessionDetail) => void
  onNewSession: (session: SessionSummary) => void
  onNetworkError: () => void
}

export function SessionBrowser({
  open,
  onClose,
  currentSessionId,
  onRestore,
  onNewSession,
  onNetworkError,
}: SessionBrowserProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setSessions(await fetchSessions())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  if (!open) return null

  async function handleNew() {
    setBusyId('new')
    try {
      const session = await createSession()
      onNewSession(session)
      await refresh()
      onClose()
    } catch (err) {
      if (err instanceof NetworkError) onNetworkError()
    } finally {
      setBusyId(null)
    }
  }

  async function handleOpen(id: string) {
    setBusyId(id)
    try {
      const detail = await fetchSession(id)
      if (detail) {
        onRestore(detail)
        onClose()
      }
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div
      className="absolute right-0 z-40 mt-2 w-80 rounded-xl border border-gray-200 bg-white p-3 shadow-xl"
      data-testid="sessions-panel"
    >
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Sessions</h2>
        <button
          type="button"
          data-testid="new-session"
          onClick={() => void handleNew()}
          disabled={busyId === 'new'}
          className="rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {busyId === 'new' ? 'Creating…' : '+ New session'}
        </button>
      </div>

      <p className="mb-2 text-[11px] text-gray-400">
        Reopen a session to restore its thread, sources, and annotations — even across days.
      </p>

      {loading ? (
        <p className="px-1 py-3 text-xs text-gray-400" data-testid="sessions-loading">
          Loading your sessions…
        </p>
      ) : sessions.length === 0 ? (
        <p className="px-1 py-3 text-xs text-gray-400" data-testid="sessions-empty">
          No saved sessions yet. Start a new one to keep your history.
        </p>
      ) : (
        <ul className="max-h-80 space-y-1.5 overflow-y-auto" data-testid="session-list">
          {sessions.map(s => {
            const isCurrent = s.session_id === currentSessionId
            return (
              <li key={s.session_id}>
                <button
                  type="button"
                  data-testid="session-item"
                  data-session-id={s.session_id}
                  onClick={() => void handleOpen(s.session_id)}
                  disabled={busyId === s.session_id}
                  className={`w-full rounded-lg border p-2.5 text-left transition-colors ${
                    isCurrent
                      ? 'border-indigo-300 bg-indigo-50/60'
                      : 'border-gray-200 bg-white hover:border-indigo-200 hover:bg-gray-50'
                  } disabled:opacity-50`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium text-gray-800">
                      {s.title || 'Untitled session'}
                      {isCurrent && <span className="ml-1.5 text-[10px] text-indigo-500">· current</span>}
                    </span>
                    {busyId === s.session_id && <span className="text-[10px] text-gray-400">Opening…</span>}
                  </span>
                  <span className="mt-0.5 flex items-center gap-2 text-[10px] text-gray-400">
                    {typeof s.dataset_count === 'number' && <span>{s.dataset_count} sources</span>}
                    {typeof s.run_count === 'number' && <span>{s.run_count} runs</span>}
                    {s.updated_at && <span>{formatDate(s.updated_at)}</span>}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <div className="mt-2 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-2 py-1 text-[11px] font-medium text-gray-500 hover:bg-gray-100"
        >
          Close
        </button>
      </div>
    </div>
  )
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
