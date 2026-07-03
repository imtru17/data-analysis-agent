'use client'

import { useState } from 'react'
import { downloadQueryCsv, ApiError, NetworkError, type QueryResult } from '@/lib/api'

// Phase-4 result table: renders the bounded {columns, rows, row_count, truncated}
// payload from POST /datasets/{id}/query with a row-count caption, a "showing
// first N (truncated)" note when the full result is larger, and a Download CSV
// button that re-runs the SAME sql server-side to fetch the FULL result as a CSV
// attachment. An empty result shows "0 rows" rather than an error.

interface ResultTableProps {
  datasetId: string
  result: QueryResult
  sql: string
  onNetworkError?: () => void
}

export function ResultTable({ datasetId, result, sql, onNetworkError }: ResultTableProps) {
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  async function download() {
    if (downloading) return
    setDownloading(true)
    setDownloadError(null)
    try {
      await downloadQueryCsv(datasetId, sql)
    } catch (err) {
      if (err instanceof NetworkError) {
        onNetworkError?.()
        setDownloadError("Can't reach the server.")
      } else if (err instanceof ApiError) {
        setDownloadError(err.message)
      } else {
        setDownloadError('Could not download the result.')
      }
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div data-testid="result-table" className="mt-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-gray-600">
          <span data-testid="result-row-count" className="font-semibold text-gray-800">
            {result.row_count.toLocaleString()}
          </span>{' '}
          row{result.row_count === 1 ? '' : 's'}
          {result.truncated && (
            <span data-testid="result-truncated" className="ml-1 text-amber-600">
              · showing first {result.rows.length.toLocaleString()} (truncated)
            </span>
          )}
        </p>
        <button
          type="button"
          data-testid="download-csv"
          onClick={() => void download()}
          disabled={downloading}
          className="rounded-md border border-gray-200 px-2.5 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {downloading ? 'Preparing…' : 'Download CSV'}
        </button>
      </div>

      {downloadError && (
        <p
          data-testid="download-error"
          className="mb-2 rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-700"
        >
          {downloadError}
        </p>
      )}

      {result.rows.length === 0 ? (
        <div
          data-testid="result-empty"
          className="rounded-lg border border-dashed border-gray-300 bg-white/60 p-4 text-center text-xs text-gray-500"
        >
          0 rows — the query ran but returned no data.
        </div>
      ) : (
        <div className="max-h-96 overflow-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full border-collapse text-sm" data-testid="result-grid">
            <thead className="sticky top-0">
              <tr className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                {result.columns.map(col => (
                  <th key={col} className="whitespace-nowrap px-3 py-1.5 font-medium">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i} className="border-t border-gray-100">
                  {result.columns.map(col => (
                    <td
                      key={col}
                      className="whitespace-nowrap px-3 py-1.5 font-mono text-xs text-gray-700"
                    >
                      {formatCell(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}
