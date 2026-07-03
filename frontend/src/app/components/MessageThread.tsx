'use client'

import { useEffect, useRef } from 'react'
import type { ChatMessage } from '@/lib/messages'
import { ProfileMessage } from './ProfileMessage'
import { AgentAnswer } from './AgentAnswer'

// The scrollable conversation. Renders each message by kind and auto-scrolls to
// the newest turn. Shows an empty-state prompt when nothing has happened yet.

export function MessageThread({ messages }: { messages: ChatMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div
        data-testid="thread-empty"
        className="flex flex-1 flex-col items-center justify-center px-6 text-center"
      >
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-xl">
          📈
        </div>
        <p className="text-sm font-medium text-gray-700">Upload a CSV to get started</p>
        <p className="mt-1 max-w-sm text-xs text-gray-400">
          Ask questions in plain English. The agent writes the pandas code and runs it
          locally — only the schema and a few sample rows ever reach the LLM.
        </p>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4" data-testid="message-thread">
      {messages.map(msg => (
        <MessageRow key={msg.id} message={msg} />
      ))}
      <div ref={endRef} />
    </div>
  )
}

function MessageRow({ message }: { message: ChatMessage }) {
  if (message.kind === 'user') {
    return (
      <div className="flex justify-end" data-testid="user-message">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">
          {message.text}
        </div>
      </div>
    )
  }

  if (message.kind === 'profile') {
    return <ProfileMessage profile={message.profile} />
  }

  if (message.kind === 'system') {
    const tone =
      message.tone === 'error'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-gray-200 bg-gray-50 text-gray-600'
    return (
      <div data-testid="system-message" className={`rounded-lg border px-4 py-3 text-sm ${tone}`}>
        {message.text}
      </div>
    )
  }

  return <AgentAnswer message={message} />
}
