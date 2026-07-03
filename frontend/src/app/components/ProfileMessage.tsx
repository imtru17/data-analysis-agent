'use client'

import type { DatasetProfile } from '@/lib/api'
import { SoonPill } from './Stub'

// System message rendered after a successful upload: filename, row count, a
// compact schema table (column -> dtype), and a bounded sample-row preview —
// exactly the schema+samples the LLM will later see. Includes the labelled
// "Suggested questions (soon)" stub chips.

export function ProfileMessage({ profile }: { profile: DatasetProfile }) {
  const columnNames = profile.columns.map(c => c.name)

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

      <div className="mt-3">
        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">Schema</p>
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full border-collapse text-sm" data-testid="schema-table">
            <thead>
              <tr className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="px-3 py-1.5 font-medium">Column</th>
                <th className="px-3 py-1.5 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {profile.columns.map(col => (
                <tr key={col.name} className="border-t border-gray-100">
                  <td className="px-3 py-1.5 font-medium text-gray-800">{col.name}</td>
                  <td className="px-3 py-1.5 font-mono text-xs text-gray-500">{col.dtype}</td>
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

      <div className="mt-3" aria-disabled="true" title="Coming soon — arrives in a later phase.">
        <div className="mb-1.5 flex items-center gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Suggested questions
          </p>
          <SoonPill />
        </div>
        <div className="flex flex-wrap gap-2 opacity-60" data-testid="suggested-questions">
          {['Summarise this dataset', 'What are the top values?', 'Any anomalies?'].map(q => (
            <span
              key={q}
              className="cursor-not-allowed rounded-full border border-dashed border-gray-300 bg-white px-3 py-1 text-xs text-gray-400"
            >
              {q}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}
