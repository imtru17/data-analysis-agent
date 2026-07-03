'use client'

import { useEffect, useState } from 'react'
import {
  fetchColumnValues,
  ApiError,
  NetworkError,
  type ColumnValues as ColumnValuesData,
} from '@/lib/api'

// Phase-4 column drill-in: opened by clicking a profile tile. Loads the clicked
// column's top values + counts (GET /datasets/{id}/columns/{col}/values) and
// renders them as a small labelled bar list, with loading + error states. A
// friendly "unknown column" (or any 400) message is shown inline — never a crash.

interface ColumnValuesProps {
  datasetId: string
  column: string
  onClose: () => void
  onNetworkError?: () => void
}

export function ColumnValues({ datasetId, column, onClose, onNetworkError }: ColumnValuesProps) {
  const [data, setData] = useState<ColumnValuesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)

    ;(async () => {
      try {
        const values = await fetchColumnValues(datasetId, column)
        if (!cancelled) setData(values)
      } catch (err) {
        if (cancelled) return
        if (err instanceof NetworkError) {
          onNetworkError?.()
          setError("Can't reach the server.")
        } else if (err instanceof ApiError) {
          setError(err.message)
        } else {
          setError('Could not load values for that column.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [datasetId, column, onNetworkError])

  const maxCount = data?.values.reduce((m, v) => Math.max(m, v.count), 0) ?? 0

  return (
    <div
      data-testid="column-values"
      data-column={column}
      className="mt-3 rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
    >
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-700">
          Top values &mdash; <span className="font-mono text-gray-800">{column}</span>
        </p>
        <button
          type="button"
          data-testid="column-values-close"
          aria-label="Close"
          onClick={onClose}
          className="rounded px-1.5 text-gray-400 hover:text-gray-700"
        >
          &times;
        </button>
      </div>

      {loading && (
        <p data-testid="column-values-loading" className="text-xs text-gray-400">
          Loading values&hellip;
        </p>
      )}

      {error && (
        <p
          data-testid="column-values-error"
          className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-700"
        >
          {error}
        </p>
      )}

      {data && !loading && !error && (
        <div>
          {data.values.length === 0 ? (
            <p data-testid="column-values-empty" className="text-xs text-gray-400">
              No values to show.
            </p>
          ) : (
            <ul className="space-y-1.5" data-testid="column-values-list">
              {data.values.map((v, i) => (
                <li key={i} data-testid="column-value-row" className="flex items-center gap-2">
                  <span
                    className="w-32 shrink-0 truncate font-mono text-[11px] text-gray-700"
                    title={formatValue(v.value)}
                  >
                    {formatValue(v.value)}
                  </span>
                  <span className="relative h-4 flex-1 overflow-hidden rounded bg-gray-100">
                    <span
                      className="absolute inset-y-0 left-0 rounded bg-indigo-300"
                      style={{ width: `${maxCount > 0 ? (v.count / maxCount) * 100 : 0}%` }}
                    />
                  </span>
                  <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-gray-600">
                    {v.count.toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-gray-400">
            {data.total.toLocaleString()} rows total
            {data.truncated ? ` · showing top ${data.values.length}` : ''}
          </p>
        </div>
      )}
    </div>
  )
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '(null)'
  if (typeof value === 'number') return value.toLocaleString()
  const s = String(value)
  return s.length === 0 ? '(empty)' : s
}
