'use client'

import { useState } from 'react'

// Phase-5 STUB (clearly labelled, NON-FUNCTIONAL). A "Dashboard" view button in
// the Data-panel toolbar. It makes NO live call — clicking it only reveals a
// short preview note describing the combined tiles + charts dashboard shipping
// in Phase 5, so a user never mistakes the disabled surface for a bug.

export function DashboardStub() {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        type="button"
        data-testid="stub-dashboard"
        data-stub="true"
        aria-disabled="true"
        title="Coming soon — a combined tiles + charts dashboard (Phase 5)"
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-gray-300 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-400"
      >
        Dashboard
        <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-500">
          Coming soon
        </span>
      </button>

      {open && (
        <div
          data-testid="stub-dashboard-note"
          className="absolute left-0 z-30 mt-1 w-64 rounded-lg border border-gray-200 bg-white p-3 text-[11px] text-gray-500 shadow-lg"
        >
          A full dashboard combining these profile tiles with multiple charts is coming in a
          later release. Nothing runs yet — this is a preview of what&apos;s next.
        </div>
      )}
    </div>
  )
}
