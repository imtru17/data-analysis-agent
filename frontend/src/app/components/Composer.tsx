'use client'

// The question composer: a textbox + Send. Disabled until a dataset is loaded
// (hint "Upload a CSV to start") and while an analysis is in flight. The
// "📊 Chart" toggle is REAL (Phase 2): when on, the analysis requests a chart.
// The composer value is controlled by the parent so follow-up chips can fill and
// send it.

interface ComposerProps {
  value: string
  onValueChange: (value: string) => void
  onSend: (question: string, wantChart: boolean) => void
  hasDataset: boolean
  inFlight: boolean
  wantChart: boolean
  onToggleChart: (on: boolean) => void
}

export function Composer({
  value,
  onValueChange,
  onSend,
  hasDataset,
  inFlight,
  wantChart,
  onToggleChart,
}: ComposerProps) {
  const disabled = !hasDataset || inFlight
  const canSend = hasDataset && !inFlight && value.trim().length > 0

  function submit() {
    if (!canSend) return
    onSend(value.trim(), wantChart)
    onValueChange('')
  }

  return (
    <div className="border-t border-gray-200 bg-white p-3">
      <div className="flex items-end gap-2">
        <button
          type="button"
          data-testid="chart-toggle"
          aria-pressed={wantChart}
          disabled={!hasDataset}
          onClick={() => onToggleChart(!wantChart)}
          title={
            wantChart
              ? 'Chart requested — the answer will include a chart when it makes sense.'
              : 'Ask for a chart with this question.'
          }
          className={`flex items-center gap-1 rounded-lg border px-2.5 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
            wantChart
              ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
              : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          📊 Chart
          {wantChart && <span aria-hidden>✓</span>}
        </button>

        <div className="relative flex-1">
          <textarea
            data-testid="composer-input"
            value={value}
            onChange={e => onValueChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            disabled={disabled}
            rows={1}
            placeholder={hasDataset ? 'Ask a question about your data…' : 'Upload a CSV to start'}
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
