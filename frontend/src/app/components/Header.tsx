'use client'

import type { ReactNode } from 'react'

// App header: title + branding, a REAL "Today: $x.xx" running cost total (Phase 2,
// from GET /cost/today), and a REAL "History" / Sessions button (Phase 3) that
// toggles the session browser rendered in `sessionsPanel`.

interface HeaderProps {
  todayCost?: number | null
  sessionsOpen: boolean
  onToggleSessions: () => void
  sessionsPanel?: ReactNode
}

export function Header({ todayCost, sessionsOpen, onToggleSessions, sessionsPanel }: HeaderProps) {
  const cost = typeof todayCost === 'number' ? todayCost : 0

  return (
    <header className="sticky top-0 z-20 border-b border-gray-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white"
          >
            DA
          </span>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold text-gray-900">Data Analysis Agent</h1>
            <p className="text-[11px] text-gray-500">Local-first · your raw data never leaves your machine</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            title="Total Anthropic spend today across all analyses."
            data-testid="today-cost"
            className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-medium text-gray-700"
          >
            Today: {formatCost(cost)}
          </span>

          <div className="relative">
            <button
              type="button"
              title="Browse and reopen your saved sessions."
              data-testid="sessions-button"
              aria-haspopup="dialog"
              aria-expanded={sessionsOpen}
              onClick={onToggleSessions}
              className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              History
            </button>
            {sessionsPanel}
          </div>
        </div>
      </div>
    </header>
  )
}

function formatCost(value: number): string {
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}
