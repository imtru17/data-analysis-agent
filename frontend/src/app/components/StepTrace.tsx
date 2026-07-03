'use client'

import type { StepChip } from '@/lib/steps'

// The live step trace: an inline row of chips that flip running(spinner) ->
// done(check) as `step` SSE events arrive. A skipped chip (fast path) is muted;
// the active chip on an error turns red.

export function StepTrace({ chips }: { chips: StepChip[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="step-trace" role="status" aria-live="polite">
      {chips.map((chip, i) => (
        <div key={chip.key} className="flex items-center gap-1.5">
          <Chip chip={chip} />
          {i < chips.length - 1 && <span className="text-gray-300" aria-hidden>›</span>}
        </div>
      ))}
    </div>
  )
}

function Chip({ chip }: { chip: StepChip }) {
  const styles: Record<StepChip['status'], string> = {
    pending: 'border-gray-200 bg-gray-50 text-gray-400',
    running: 'border-indigo-300 bg-indigo-50 text-indigo-700',
    done: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    skipped: 'border-gray-200 bg-gray-50 text-gray-400 line-through',
    error: 'border-red-300 bg-red-50 text-red-700',
  }

  return (
    <span
      data-testid={`step-chip-${chip.key}`}
      data-status={chip.status}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${styles[chip.status]}`}
    >
      <StatusIcon status={chip.status} />
      {chip.label}
      {chip.status === 'skipped' && <span className="text-[10px] no-underline">(skipped)</span>}
    </span>
  )
}

function StatusIcon({ status }: { status: StepChip['status'] }) {
  if (status === 'running') {
    return (
      <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden>
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
    )
  }
  if (status === 'done') {
    return (
      <svg className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
        <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.1 3.1 6.8-6.8a1 1 0 011.4 0z" clipRule="evenodd" />
      </svg>
    )
  }
  if (status === 'error') {
    return (
      <svg className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.7 7.3a1 1 0 011.4 0L10 8.6l1.3-1.3a1 1 0 111.4 1.4L11.4 10l1.3 1.3a1 1 0 01-1.4 1.4L10 11.4l-1.3 1.3a1 1 0 01-1.4-1.4L8.6 10 7.3 8.7a1 1 0 010-1.4z" clipRule="evenodd" />
      </svg>
    )
  }
  return <span className="h-1.5 w-1.5 rounded-full bg-current opacity-40" aria-hidden />
}
