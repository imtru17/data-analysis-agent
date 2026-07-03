'use client'

// Phase-5 STUB (clearly labelled, NON-FUNCTIONAL). A preview card for the
// interactive, rotatable 3D chart shipping in Phase 5. It renders a static
// placeholder with a "Coming soon" badge and makes NO live call — a labelled
// preview so the user sees the direction without mistaking it for a broken chart.

export function Chart3dStub() {
  return (
    <div
      data-testid="stub-chart3d"
      data-stub="true"
      className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          3D chart
        </span>
        <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-500">
          Coming soon
        </span>
      </div>

      <div
        aria-hidden
        className="flex h-32 items-center justify-center rounded-md border border-gray-200 bg-white/60 bg-[linear-gradient(135deg,transparent_46%,#e5e7eb_47%,#e5e7eb_53%,transparent_54%)] bg-[length:14px_14px]"
      >
        <span className="text-4xl text-gray-300">◲</span>
      </div>

      <p className="mt-2 text-[11px] text-gray-400">
        Coming soon — a rotatable, interactive 3D chart (drag to rotate; pick x/y/z axes),
        rendered locally. No live preview yet.
      </p>
    </div>
  )
}
