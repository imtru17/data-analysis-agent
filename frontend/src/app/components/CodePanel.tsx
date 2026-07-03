'use client'

import { useState } from 'react'

// Collapsible "Show code" disclosure under an answer. Reveals the EXACT pandas
// snippet the agent ran (monospace) with a copy button. Collapsed by default.

export function CodePanel({ code }: { code: string }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="mt-2">
      <button
        type="button"
        data-testid="show-code-toggle"
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
      >
        <span aria-hidden className={`transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
        {open ? 'Hide code' : 'Show code'}
      </button>

      {open && (
        <div
          data-testid="code-panel"
          className="mt-1.5 overflow-hidden rounded-lg border border-gray-800 bg-gray-900"
        >
          <div className="flex items-center justify-between border-b border-gray-700 px-3 py-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
              pandas · ran locally
            </span>
            <button
              type="button"
              data-testid="copy-code"
              onClick={copy}
              className="rounded px-2 py-0.5 text-[11px] font-medium text-gray-300 hover:bg-gray-700"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <pre className="overflow-x-auto px-3 py-2.5 text-xs leading-relaxed text-gray-100">
            <code data-testid="code-content">{code}</code>
          </pre>
        </div>
      )}
    </div>
  )
}
