'use client'

import { useState } from 'react'
import type { Source } from '@/lib/api'

// Real Phase-3 multi-source panel (replaces the Phase-1 "Coming soon" rail). It
// lists every loaded source — uploaded files AND live DB connections — with a
// checkbox picker so the user can pin one or MORE for the next question. The
// selected source ids are sent with the analysis. "+ Add source" is now real:
// it reveals two actions — upload a file, or connect a database.

interface SourcePanelProps {
  sources: Source[]
  selectedIds: Set<string>
  onToggleSelect: (id: string) => void
  onUploadClick: () => void
  onConnectDb: () => void
}

export function SourcePanel({
  sources,
  selectedIds,
  onToggleSelect,
  onUploadClick,
  onConnectDb,
}: SourcePanelProps) {
  const [addOpen, setAddOpen] = useState(false)

  return (
    <aside
      data-testid="source-panel"
      className="hidden w-72 shrink-0 overflow-y-auto border-l border-gray-200 bg-gray-50/50 p-4 lg:block"
    >
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Sources</h2>
        <div className="relative">
          <button
            type="button"
            data-testid="add-source"
            onClick={() => setAddOpen(v => !v)}
            aria-expanded={addOpen}
            aria-haspopup="menu"
            className="flex items-center gap-1 rounded-md border border-indigo-200 bg-white px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-50"
          >
            + Add source
          </button>
          {addOpen && (
            <div
              role="menu"
              data-testid="add-source-menu"
              className="absolute right-0 z-30 mt-1 w-44 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
            >
              <button
                type="button"
                role="menuitem"
                data-testid="add-source-upload"
                onClick={() => {
                  setAddOpen(false)
                  onUploadClick()
                }}
                className="block w-full px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-100"
              >
                📄 Upload a file
              </button>
              <button
                type="button"
                role="menuitem"
                data-testid="connect-db-button"
                onClick={() => {
                  setAddOpen(false)
                  onConnectDb()
                }}
                className="block w-full px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-100"
              >
                🗄️ Connect a database
              </button>
            </div>
          )}
        </div>
      </div>

      <p className="mb-3 text-[11px] text-gray-400">
        Pick one or more sources for your next question. The agent auto-picks and joins across
        the checked sources.
      </p>

      {sources.length === 0 ? (
        <div
          data-testid="source-panel-empty"
          className="rounded-lg border border-dashed border-gray-300 bg-white/60 p-4 text-center"
        >
          <p className="text-xs font-medium text-gray-600">No sources yet</p>
          <p className="mt-1 text-[11px] text-gray-400">
            Upload a file or connect a database to get started.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {sources.map(src => {
            const checked = selectedIds.has(src.id)
            return (
              <li key={src.id} data-testid="source-item" data-source-kind={src.kind}>
                <label
                  className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 transition-colors ${
                    checked
                      ? 'border-indigo-300 bg-indigo-50/60'
                      : 'border-gray-200 bg-white hover:border-indigo-200'
                  }`}
                >
                  <input
                    type="checkbox"
                    data-testid="source-checkbox"
                    checked={checked}
                    onChange={() => onToggleSelect(src.id)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span aria-hidden>{src.kind === 'db' ? '🗄️' : '📄'}</span>
                      <span className="truncate text-xs font-medium text-gray-800">{src.name}</span>
                    </span>
                    {src.detail && (
                      <span className="mt-0.5 block truncate font-mono text-[10px] text-gray-400">
                        {src.detail}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}
