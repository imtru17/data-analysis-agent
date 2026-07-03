'use client'

import { useEffect, useRef, useState } from 'react'
import { exportUrl, type ExportKind } from '@/lib/api'

// Real "Export ▾" dropdown in the answer toolbar (replaces the Phase-1 stub).
// Each item is an anchor whose href points at GET /analyses/{run_id}/export?kind=…
// with a `download` attribute, so clicking triggers a browser download of the
// cleaned CSV/Parquet, the code, or the shareable report — targeting this run.

const ITEMS: { kind: ExportKind; label: string; testId: string }[] = [
  { kind: 'csv', label: 'Cleaned data (CSV)', testId: 'export-csv' },
  { kind: 'parquet', label: 'Cleaned data (Parquet)', testId: 'export-parquet' },
  { kind: 'code', label: 'Code', testId: 'export-code' },
  { kind: 'report', label: 'Report', testId: 'export-report' },
]

export function ExportMenu({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        data-testid="export-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
      >
        Export
        <span aria-hidden className={`transition-transform ${open ? 'rotate-180' : ''}`}>▾</span>
      </button>

      {open && (
        <div
          role="menu"
          data-testid="export-dropdown"
          className="absolute left-0 z-30 mt-1 w-52 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
        >
          {ITEMS.map(item => (
            <a
              key={item.kind}
              role="menuitem"
              data-testid={item.testId}
              href={exportUrl(runId, item.kind)}
              download
              onClick={() => setOpen(false)}
              className="block px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-100"
            >
              {item.label}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
