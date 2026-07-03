'use client'

import { useState } from 'react'
import { SoonPill, StubButton } from './Stub'

// App header: title + real branding, plus two clearly-labelled stubs — the
// "Today: —" cost placeholder and a History button that opens a disabled panel.

export function Header() {
  const [historyOpen, setHistoryOpen] = useState(false)

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
            aria-disabled="true"
            title="Coming soon — arrives in a later phase."
            data-testid="today-cost"
            className="flex cursor-not-allowed items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-medium text-gray-400 opacity-60"
          >
            Today: —
            <SoonPill />
          </span>

          <div className="relative">
            <button
              type="button"
              aria-disabled="true"
              title="Coming soon — arrives in a later phase."
              data-testid="history-button"
              onClick={() => setHistoryOpen(v => !v)}
              className="flex cursor-not-allowed items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-medium text-gray-500 opacity-60"
            >
              History
              <SoonPill />
            </button>
            {historyOpen && (
              <div
                data-testid="history-panel"
                className="absolute right-0 mt-2 w-60 rounded-lg border border-gray-200 bg-white p-4 text-center shadow-lg"
              >
                <p className="text-sm font-medium text-gray-600">Your past sessions</p>
                <p className="mt-1 text-xs text-gray-400">
                  Cross-day session history arrives in a later phase.
                </p>
                <SoonPill className="mt-2" />
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
