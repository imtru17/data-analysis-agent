'use client'

import type { ColumnProfile, DatasetProfile } from '@/lib/api'

// System message rendered after a successful upload. Phase 2 turns this into a
// real insight surface: the richer per-column profile (null %, distinct count,
// numeric min/max/mean) plus a bounded sample-row preview — exactly the schema +
// samples the LLM will later see — and REAL clickable follow-up-question chips
// (was the greyed "Suggested questions" stub). Clicking a chip sends that
// question via `onFollowup`.

interface ProfileMessageProps {
  profile: DatasetProfile
  onFollowup?: (question: string) => void
  followupsDisabled?: boolean
}

export function ProfileMessage({ profile, onFollowup, followupsDisabled }: ProfileMessageProps) {
  const columnNames = profile.columns.map(c => c.name)
  const followups = profile.followups ?? []

  return (
    <div
      data-testid="profile-message"
      className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <span className="font-semibold text-emerald-800">Loaded {profile.filename}</span>
        <span className="text-emerald-700">
          · {profile.row_count.toLocaleString()} rows · {profile.columns.length} columns
        </span>
      </div>

      {/* Richer auto-profile card (Phase 2). */}
      <div className="mt-3" data-testid="profile-card">
        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
          Column profile
        </p>
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full border-collapse text-sm" data-testid="schema-table">
            <thead>
              <tr className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="px-3 py-1.5 font-medium">Column</th>
                <th className="px-3 py-1.5 font-medium">Type</th>
                <th className="px-3 py-1.5 font-medium">Null %</th>
                <th className="px-3 py-1.5 font-medium">Distinct</th>
                <th className="px-3 py-1.5 font-medium">Min</th>
                <th className="px-3 py-1.5 font-medium">Max</th>
                <th className="px-3 py-1.5 font-medium">Mean</th>
              </tr>
            </thead>
            <tbody>
              {profile.columns.map(col => (
                <tr key={col.name} className="border-t border-gray-100">
                  <td className="px-3 py-1.5 font-medium text-gray-800">{col.name}</td>
                  <td className="px-3 py-1.5 font-mono text-xs text-gray-500">{col.dtype}</td>
                  <td className="px-3 py-1.5 text-gray-600">{nullPct(col, profile.row_count)}</td>
                  <td className="px-3 py-1.5 text-gray-600">{numOrDash(col.distinct)}</td>
                  <td className="px-3 py-1.5 text-gray-600">{valueOrDash(col.min)}</td>
                  <td className="px-3 py-1.5 text-gray-600">{valueOrDash(col.max)}</td>
                  <td className="px-3 py-1.5 text-gray-600">{meanOrDash(col.mean)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {profile.sample_rows.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            {profile.sample_rows.length} sample rows
          </p>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full border-collapse text-sm" data-testid="sample-table">
              <thead>
                <tr className="bg-gray-50 text-left text-xs text-gray-500">
                  {columnNames.map(name => (
                    <th key={name} className="whitespace-nowrap px-3 py-1.5 font-medium">
                      {name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {profile.sample_rows.map((row, i) => (
                  <tr key={i} className="border-t border-gray-100">
                    {columnNames.map(name => (
                      <td key={name} className="whitespace-nowrap px-3 py-1.5 text-gray-700">
                        {formatCell(row[name])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Real follow-up chips (Phase 2). */}
      {followups.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Suggested questions
          </p>
          <div className="flex flex-wrap gap-2" data-testid="suggested-questions">
            {followups.map(q => (
              <button
                key={q}
                type="button"
                data-testid="followup-chip"
                disabled={followupsDisabled}
                onClick={() => onFollowup?.(q)}
                className="rounded-full border border-indigo-200 bg-white px-3 py-1 text-xs font-medium text-indigo-700 shadow-sm transition-colors hover:border-indigo-400 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

function nullPct(col: ColumnProfile, rowCount: number): string {
  if (col.null_count === undefined || rowCount <= 0) return '—'
  const pct = (col.null_count / rowCount) * 100
  return pct === 0 ? '0%' : `${pct < 0.1 ? '<0.1' : pct.toFixed(1)}%`
}

function numOrDash(value: number | undefined): string {
  return value === undefined ? '—' : value.toLocaleString()
}

function valueOrDash(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return roundNum(value)
  return String(value)
}

function meanOrDash(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return roundNum(value)
}

function roundNum(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString()
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
