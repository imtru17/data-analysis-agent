// Shared "coming soon" marking primitives. Every non-functional Phase-1 stub is
// rendered through these so a stub reads as intentionally inert — never as a bug.
// Convention: reduced opacity, a "Soon" pill, not-allowed cursor, aria-disabled,
// a "Coming soon" tooltip, and a click that does nothing (no request).

import type { ReactNode } from 'react'

const TOOLTIP = 'Coming soon — arrives in a later phase.'

export function SoonPill({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 ${className}`}
      data-testid="soon-pill"
    >
      Soon
    </span>
  )
}

interface StubButtonProps {
  children: ReactNode
  className?: string
  testId?: string
  showPill?: boolean
}

/** A visually-inert button that shows a Soon pill and never fires a request. */
export function StubButton({ children, className = '', testId, showPill = true }: StubButtonProps) {
  return (
    <button
      type="button"
      aria-disabled="true"
      disabled
      title={TOOLTIP}
      data-testid={testId}
      onClick={e => e.preventDefault()}
      className={`inline-flex cursor-not-allowed items-center gap-1.5 opacity-60 ${className}`}
    >
      {children}
      {showPill && <SoonPill />}
    </button>
  )
}

interface StubCardProps {
  title: string
  desc: string
  icon?: string
  testId?: string
}

/** A disabled "coming soon" card for the right rail. */
export function StubCard({ title, desc, icon, testId }: StubCardProps) {
  return (
    <div
      aria-disabled="true"
      title={TOOLTIP}
      data-testid={testId}
      className="cursor-not-allowed rounded-lg border border-dashed border-gray-300 bg-white/60 p-3 opacity-60"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium text-gray-700">
          {icon && <span aria-hidden>{icon}</span>}
          {title}
        </span>
        <SoonPill />
      </div>
      <p className="mt-1 text-xs leading-snug text-gray-500">{desc}</p>
    </div>
  )
}
