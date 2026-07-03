'use client'

import { useEffect, useState } from 'react'
import {
  fetchTiles,
  ApiError,
  NetworkError,
  type DatasetTiles,
  type QueryResult,
  type Source,
} from '@/lib/api'
import { ProfileTiles } from './ProfileTiles'
import { ColumnValues } from './ColumnValues'
import { SqlQueryBox } from './SqlQueryBox'
import { ResultTable } from './ResultTable'
import { DashboardStub } from './DashboardStub'
import { Chart3dStub } from './Chart3dStub'
import { ConnectCreateTableStub } from './ConnectCreateTableStub'

// Phase-4 Data workbench: an entirely LOCAL (no-LLM) surface for a loaded FILE
// dataset. It loads profile tiles (GET /datasets/{id}/tiles), lets the user drill
// into a column's value counts, run raw DuckDB SQL over the frame, view + download
// the result, and previews the three labelled Phase-5 stubs. It targets the most
// recent FILE source, with a selector when several files are loaded.

interface WorkbenchProps {
  fileSources: Source[]
  onNetworkError?: () => void
}

export function Workbench({ fileSources, onNetworkError }: WorkbenchProps) {
  // Default to the most recently added file source (last in the list).
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [tiles, setTiles] = useState<DatasetTiles | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null)
  const [result, setResult] = useState<{ data: QueryResult; sql: string } | null>(null)

  // Keep the active dataset valid as sources change; prefer the newest file.
  useEffect(() => {
    if (fileSources.length === 0) {
      setDatasetId(null)
      return
    }
    setDatasetId(prev => {
      if (prev && fileSources.some(s => s.id === prev)) return prev
      return fileSources[fileSources.length - 1].id
    })
  }, [fileSources])

  // Load tiles whenever the active dataset changes.
  useEffect(() => {
    if (!datasetId) {
      setTiles(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setTiles(null)
    setSelectedColumn(null)
    setResult(null)

    ;(async () => {
      try {
        const data = await fetchTiles(datasetId)
        if (!cancelled) setTiles(data)
      } catch (err) {
        if (cancelled) return
        if (err instanceof NetworkError) {
          onNetworkError?.()
          setError("Can't reach the server — is it running on :8001?")
        } else if (err instanceof ApiError) {
          setError(err.message)
        } else {
          setError('Could not load the profile tiles for this dataset.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [datasetId, onNetworkError])

  if (fileSources.length === 0) {
    return (
      <div
        data-testid="workbench-empty"
        className="flex flex-1 flex-col items-center justify-center px-6 text-center"
      >
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-xl">
          ▦
        </div>
        <p className="text-sm font-medium text-gray-700">Upload a CSV to use the workbench</p>
        <p className="mt-1 max-w-sm text-xs text-gray-400">
          The Data workbench gives you clickable profile tiles and a local SQL query box for any
          loaded file — all running on your machine, no LLM call.
        </p>
      </div>
    )
  }

  return (
    <div data-testid="workbench" className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
      {/* Toolbar: dataset selector (when >1 file) + Phase-5 stubs. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {fileSources.length > 1 && (
            <select
              data-testid="workbench-dataset-select"
              value={datasetId ?? ''}
              onChange={e => setDatasetId(e.target.value)}
              className="rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs text-gray-700"
            >
              {fileSources.map(s => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
          <DashboardStub />
        </div>
        <ConnectCreateTableStub />
      </div>

      {loading && (
        <p data-testid="workbench-loading" className="text-xs text-gray-400">
          Loading profile tiles&hellip;
        </p>
      )}

      {error && (
        <div
          data-testid="workbench-error"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {error}
        </div>
      )}

      {tiles && !error && (
        <>
          <ProfileTiles
            tiles={tiles}
            selectedColumn={selectedColumn}
            onSelectColumn={col => setSelectedColumn(prev => (prev === col ? null : col))}
          />

          {selectedColumn && datasetId && (
            <ColumnValues
              datasetId={datasetId}
              column={selectedColumn}
              onClose={() => setSelectedColumn(null)}
              onNetworkError={onNetworkError}
            />
          )}

          {datasetId && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <SqlQueryBox
                datasetId={datasetId}
                onResult={(data, sql) => setResult({ data, sql })}
                onNetworkError={onNetworkError}
              />
              {result && (
                <ResultTable
                  datasetId={datasetId}
                  result={result.data}
                  sql={result.sql}
                  onNetworkError={onNetworkError}
                />
              )}
            </div>
          )}

          {/* Phase-5 preview card. */}
          <Chart3dStub />
        </>
      )}
    </div>
  )
}
