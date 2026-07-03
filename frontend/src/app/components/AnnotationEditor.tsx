'use client'

import { useState } from 'react'
import { saveDatasetAnnotation, ApiError, NetworkError } from '@/lib/api'

// Real Phase-3 inline column-annotation editor (replaces the Phase-1 stub). It
// sits on each column of the profile/schema table: a "✎" button opens a small
// editor; saving upserts the business note (PUT /datasets/{id}/columns/{col}/
// annotation). The saved note then shows under the column and is used by the
// agent on the next ask.

interface AnnotationEditorProps {
  datasetId: string
  column: string
  initialNote?: string
  onNetworkError?: () => void
}

export function AnnotationEditor({
  datasetId,
  column,
  initialNote = '',
  onNetworkError,
}: AnnotationEditorProps) {
  const [note, setNote] = useState(initialNote)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(initialNote)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const saved = await saveDatasetAnnotation(datasetId, column, draft.trim())
      setNote(saved.note)
      setEditing(false)
    } catch (err) {
      if (err instanceof NetworkError) {
        onNetworkError?.()
        setError("Can't reach the server.")
      } else if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Could not save the note.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <span className="mt-1 flex flex-col gap-1">
        <span className="flex items-center gap-1">
          <input
            type="text"
            data-testid="annotation-input"
            value={draft}
            autoFocus
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') void save()
              if (e.key === 'Escape') setEditing(false)
            }}
            placeholder="Business meaning…"
            className="w-40 rounded border border-gray-300 px-1.5 py-0.5 text-[11px] focus:border-indigo-500 focus:outline-none"
          />
          <button
            type="button"
            data-testid="annotation-save"
            onClick={() => void save()}
            disabled={busy}
            className="rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? '…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded px-1 text-[10px] text-gray-400 hover:text-gray-600"
          >
            ✕
          </button>
        </span>
        {error && <span className="text-[10px] text-red-500">{error}</span>}
      </span>
    )
  }

  return (
    <span className="mt-0.5 flex flex-col">
      <button
        type="button"
        data-testid="annotate-column"
        data-column={column}
        title={note ? 'Edit business note' : 'Add a business note'}
        onClick={() => {
          setDraft(note)
          setEditing(true)
        }}
        className="inline-flex items-center gap-0.5 self-start rounded px-1 py-0.5 text-[10px] font-medium text-indigo-600 hover:bg-indigo-50"
      >
        <span aria-hidden>✎</span>
        {note ? 'Edit note' : 'Annotate'}
      </button>
      {note && (
        <span
          data-testid="annotation-note"
          data-column={column}
          className="mt-0.5 max-w-[12rem] text-[10px] italic leading-snug text-gray-500"
        >
          {note}
        </span>
      )}
    </span>
  )
}
