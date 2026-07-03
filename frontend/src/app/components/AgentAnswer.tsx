'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AgentMessage } from '@/lib/messages'
import { StepTrace } from './StepTrace'
import { CodePanel } from './CodePanel'
import { SoonPill, StubButton } from './Stub'

// A single agent turn: the live step trace, then (on done) the plain-language
// answer rendered as markdown, an optional low-confidence badge, the collapsible
// code panel, and the labelled meta/export/chart stubs.

export function AgentAnswer({ message }: { message: AgentMessage }) {
  const streaming = message.status === 'streaming'
  const failed = message.status === 'failed'

  return (
    <div
      data-testid="agent-message"
      data-status={message.status}
      className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
    >
      <StepTrace chips={message.chips} />

      {failed && (
        <div
          data-testid="agent-error"
          className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          <p className="font-medium">The analysis couldn&apos;t complete.</p>
          <p className="mt-0.5">{message.errorText}</p>
          <p className="mt-1 text-xs text-red-500">Try rephrasing your question and asking again.</p>
        </div>
      )}

      {!failed && message.answer && (
        <div className="mt-3">
          {message.lowConfidence && (
            <div
              data-testid="low-confidence-badge"
              className="mb-2 inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700"
            >
              ⚠ best guess
            </div>
          )}
          <div
            data-testid="answer-text"
            className="prose prose-sm max-w-none text-[15px] leading-relaxed text-gray-800 [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5 [&_strong]:font-semibold [&_strong]:text-gray-900 [&_table]:my-2 [&_td]:border [&_td]:border-gray-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-gray-200 [&_th]:bg-gray-50 [&_th]:px-2 [&_th]:py-1"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.answer}</ReactMarkdown>
          </div>

          {message.lowConfidence && message.lowConfidenceNote && (
            <p className="mt-1.5 text-xs italic text-amber-600" data-testid="low-confidence-note">
              {message.lowConfidenceNote}
            </p>
          )}

          {message.code && <CodePanel code={message.code} />}

          {/* Labelled stubs: answer meta, export menu, chart card. */}
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-2">
            <span
              aria-disabled="true"
              title="Coming soon — arrives in a later phase."
              data-testid="answer-meta"
              className="cursor-not-allowed text-[11px] text-gray-400 opacity-60"
            >
              tokens/cost —
            </span>
            <StubButton
              testId="export-menu"
              className="rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-500"
            >
              Export ▾
            </StubButton>
          </div>

          <div
            aria-disabled="true"
            title="Coming soon — arrives in a later phase."
            data-testid="chart-card"
            className="mt-2 flex cursor-not-allowed items-center justify-between rounded-lg border border-dashed border-gray-300 bg-gray-50/60 px-3 py-2 opacity-60"
          >
            <span className="text-xs text-gray-500">📊 Charts appear here</span>
            <SoonPill />
          </div>
        </div>
      )}

      {streaming && !message.answer && (
        <p className="mt-3 text-sm text-gray-400">Working on your answer…</p>
      )}
    </div>
  )
}
