'use client'

import { useState } from 'react'

// Phase-5 STUB (clearly labelled, NON-FUNCTIONAL). A "Connect & create table"
// action targeting AWS S3 / Snowflake / another DB. It opens a config-form
// PREVIEW in an "add credentials / coming soon" state and makes NO live call —
// the submit is a disabled no-op, and an explicit note warns that this would
// send data to the cloud (cloud is opt-in, never a hidden default).

const TARGETS = [
  { value: 's3', label: 'AWS S3' },
  { value: 'snowflake', label: 'Snowflake' },
  { value: 'other', label: 'Another database' },
]

export function ConnectCreateTableStub() {
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState('s3')

  return (
    <div className="relative">
      <button
        type="button"
        data-testid="stub-connect-create-table"
        data-stub="true"
        aria-disabled="true"
        title="Coming soon — create a cloud table from this dataset (add credentials)"
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-gray-300 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-400"
      >
        Connect &amp; create table
        <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-500">
          Coming soon
        </span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Connect and create table (preview)"
          data-testid="stub-connect-create-table-form"
          className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
        >
          <p className="mb-2 text-xs font-semibold text-gray-700">
            Create a table in the cloud
            <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-700">
              Add credentials
            </span>
          </p>

          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-medium text-gray-500">Target</span>
            <select
              data-testid="stub-connect-target"
              value={target}
              onChange={e => setTarget(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs text-gray-600"
            >
              {TARGETS.map(t => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>

          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-medium text-gray-500">Credentials</span>
            <input
              type="text"
              disabled
              placeholder="add credentials to enable (coming soon)"
              className="w-full cursor-not-allowed rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs text-gray-400"
            />
          </label>

          <p
            data-testid="stub-cloud-warning"
            className="mb-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-700"
          >
            Note: this would send your data to the cloud. Cloud is opt-in — nothing is uploaded
            today. This preview makes no live call.
          </p>

          <button
            type="button"
            data-testid="stub-connect-submit"
            disabled
            className="w-full cursor-not-allowed rounded-lg bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-400"
          >
            Create table (coming soon)
          </button>
        </div>
      )}
    </div>
  )
}
