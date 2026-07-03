'use client'

import { StubCard } from './Stub'

// The right-rail "Coming soon" panel: restates the full roadmap as disabled
// cards so the user sees the vision at a glance. Every card is a labelled stub.

// Phase 2 delivered Charts, Exports/Report, Auto-profile/follow-ups, and
// Cost/daily-total — those are now REAL, so they are removed from this rail.
// Only the still-deferred Phase-3 features remain as labelled stubs.
const CARDS: { title: string; desc: string; icon: string; testId: string }[] = [
  { title: 'Connect a database', desc: 'Query a live Postgres/MySQL/SQLite database with SQL pushdown.', icon: '🗄️', testId: 'rail-connect-db' },
  { title: 'Multiple sources', desc: 'Load several files and join or compare across them.', icon: '🔗', testId: 'rail-multi-source' },
  { title: 'Sessions & history', desc: 'Persistent cross-day sessions and a browsable run history.', icon: '🕑', testId: 'rail-sessions' },
  { title: 'More file formats', desc: 'Excel, JSON, Parquet, PDF, and log/text ingestion.', icon: '📁', testId: 'rail-formats' },
]

export function ComingSoonRail() {
  return (
    <aside
      data-testid="coming-soon-rail"
      className="hidden w-72 shrink-0 overflow-y-auto border-l border-gray-200 bg-gray-50/50 p-4 lg:block"
    >
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">Coming soon</h2>
      <p className="mb-3 text-xs text-gray-400">Charts, exports, auto-profiling, and cost tracking are live. These arrive next.</p>
      <div className="space-y-2.5">
        {CARDS.map(card => (
          <StubCard key={card.testId} {...card} />
        ))}
      </div>
    </aside>
  )
}
