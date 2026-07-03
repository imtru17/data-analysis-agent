'use client'

import { useRef, useState } from 'react'
import {
  uploadDataset,
  fetchProfile,
  ApiError,
  NetworkError,
  type ColumnProfile,
  type DatasetProfile,
} from '@/lib/api'
import { SoonPill } from './Stub'

const MAX_UPLOAD_MB = 500

interface UploadControlProps {
  onUploading: (busy: boolean) => void
  onProfile: (profile: DatasetProfile) => void
  onReject: (message: string) => void
  onNetworkError: () => void
  busy: boolean
  hasDataset: boolean
}

// Real Phase-1 upload control: CSV file input + drag-drop, with real client-side
// validation. Non-CSV / too-large files are rejected with a friendly inline
// message; parse failures surface the backend's message. "+ Add source" is a
// labelled stub.

export function UploadControl({
  onUploading,
  onProfile,
  onReject,
  onNetworkError,
  busy,
  hasDataset,
}: UploadControlProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  async function handleFile(file: File) {
    const name = file.name.toLowerCase()
    if (!name.endsWith('.csv')) {
      onReject(
        `Couldn't read that file: "${file.name}" isn't a CSV. Phase 1 supports CSV up to ${MAX_UPLOAD_MB} MB.`,
      )
      return
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      onReject(
        `Couldn't read that file: it's larger than ${MAX_UPLOAD_MB} MB. Phase 1 supports CSV up to ${MAX_UPLOAD_MB} MB.`,
      )
      return
    }

    onUploading(true)
    try {
      const profile = await uploadDataset(file)
      // Phase 2: enrich with the richer per-column stats + follow-up suggestions.
      // If the profile endpoint is unavailable the basic profile still renders.
      const rich = await fetchProfile(profile.dataset_id)
      if (rich) {
        const byName = new Map<string, ColumnProfile>(
          rich.profile.columns.map(c => [c.name, c]),
        )
        profile.columns = profile.columns.map(c => ({ ...c, ...(byName.get(c.name) ?? {}) }))
        if (rich.followups?.length) profile.followups = rich.followups
      }
      onProfile(profile)
    } catch (err) {
      if (err instanceof NetworkError) {
        onNetworkError()
      } else if (err instanceof ApiError) {
        onReject(`Couldn't read that file: ${err.message}. Phase 1 supports CSV up to ${MAX_UPLOAD_MB} MB.`)
      } else {
        onReject('Couldn\'t read that file: an unexpected error occurred.')
      }
    } finally {
      onUploading(false)
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) void handleFile(file)
    e.target.value = ''
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (busy) return
    const file = e.dataTransfer.files?.[0]
    if (file) void handleFile(file)
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          {hasDataset ? 'Dataset loaded' : 'Load a dataset'}
        </span>
        <button
          type="button"
          aria-disabled="true"
          disabled
          title="Coming soon — arrives in a later phase."
          data-testid="add-source"
          onClick={e => e.preventDefault()}
          className="flex cursor-not-allowed items-center gap-1.5 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-500 opacity-60"
        >
          + Add source
          <SoonPill />
        </button>
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a CSV file"
        data-testid="upload-dropzone"
        onClick={() => !busy && inputRef.current?.click()}
        onKeyDown={e => {
          if ((e.key === 'Enter' || e.key === ' ') && !busy) {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
        onDragOver={e => {
          e.preventDefault()
          if (!busy) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-400 ${
          dragging ? 'border-indigo-400 bg-indigo-50' : 'border-gray-300 hover:border-indigo-300 hover:bg-gray-50'
        } ${busy ? 'pointer-events-none opacity-60' : ''}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          data-testid="file-input"
          onChange={onInputChange}
          disabled={busy}
        />
        {busy ? (
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <Spinner />
            Reading and profiling your file…
          </div>
        ) : (
          <>
            <span className="text-sm font-medium text-gray-700">
              Drop a CSV here, or click to browse
            </span>
            <span className="mt-1 text-xs text-gray-400">
              CSV now · Excel/JSON/Parquet/PDF/logs soon
            </span>
          </>
        )}
      </div>
    </div>
  )
}

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin text-indigo-500" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  )
}
