'use client'

import { useState } from 'react'
import { SoonPill } from './Stub'

// The question composer: a textbox + Send. Disabled until a dataset is loaded
// (hint "Upload a CSV to start") and while an analysis is in flight. The
// "📊 Chart" toggle is a labelled stub.

interface ComposerProps {
  onSend: (question: string) => void
  hasDataset: boolean
  inFlight: boolean
}

export function Composer({ onSend, hasDataset, inFlight }: ComposerProps) {
  const [value, setValue] = useState('')
  const disabled = !hasDataset || inFlight
  const canSend = hasDataset && !inFlight && value.trim().length > 0

  function submit() {
    if (!canSend) return
    onSend(value.trim())
    setValue('')
  }

  return (
    <div className="border-t border-gray-200 bg-white p-3">
      <div className="flex items-end gap-2">
        <button
          type="button"
          aria-disabled="true"
          disabled
          title="Coming soon — arrives in a later phase."
          data-testid="chart-toggle"
          onClick={e => e.preventDefault()}
          className="flex cursor-not-allowed items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-2 text-xs text-gray-500 opacity-60"
        >
          📊 Chart
          <SoonPill />
        </button>

        <div className="relative flex-1">
          <textarea
            data-testid="composer-input"
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            disabled={disabled}
            rows={1}
            placeholder={
              hasDataset ? 'Ask a question about your data…' : 'Upload a CSV to start'
            }
            className="max-h-40 w-full resize-none rounded-lg border border-gray-300 px-3 py-2.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-400"
          />
        </div>

        <button
          type="button"
          data-testid="send-button"
          onClick={submit}
          disabled={!canSend}
          className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {inFlight ? 'Working…' : 'Send'}
        </button>
      </div>
      {!hasDataset && (
        <p className="mt-1.5 px-1 text-xs text-gray-400" data-testid="composer-hint">
          Upload a CSV to start asking questions.
        </p>
      )}
    </div>
  )
}
