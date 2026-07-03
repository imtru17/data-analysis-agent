'use client'

import { useCallback, useRef, useState } from 'react'
import {
  streamAnalysis,
  NetworkError,
  ApiError,
  type DatasetProfile,
  type StepEvent,
  type DoneEvent,
  type StreamErrorEvent,
} from '@/lib/api'
import { applyStep, initialChips, markError } from '@/lib/steps'
import {
  newId,
  type AgentMessage,
  type ChatMessage,
} from '@/lib/messages'
import { Header } from './components/Header'
import { UploadControl } from './components/UploadControl'
import { MessageThread } from './components/MessageThread'
import { Composer } from './components/Composer'
import { ComingSoonRail } from './components/ComingSoonRail'
import { Toast } from './components/Toast'

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [dataset, setDataset] = useState<DatasetProfile | null>(null)
  const [uploading, setUploading] = useState(false)
  const [inFlight, setInFlight] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const datasetRef = useRef<DatasetProfile | null>(null)

  const patchAgent = useCallback((id: string, patch: (m: AgentMessage) => AgentMessage) => {
    setMessages(prev =>
      prev.map(m => (m.id === id && m.kind === 'agent' ? patch(m) : m)),
    )
  }, [])

  const handleProfile = useCallback((profile: DatasetProfile) => {
    setDataset(profile)
    datasetRef.current = profile
    setMessages(prev => [...prev, { id: newId('profile'), kind: 'profile', profile }])
  }, [])

  const handleReject = useCallback((text: string) => {
    setMessages(prev => [...prev, { id: newId('sys'), kind: 'system', text, tone: 'error' }])
  }, [])

  const handleNetworkError = useCallback(() => {
    setToast("Can't reach the server — is it running on :8001?")
  }, [])

  const handleSend = useCallback(
    async (question: string) => {
      const ds = datasetRef.current
      if (!ds || inFlight) return

      const agentId = newId('agent')
      const agentMsg: AgentMessage = {
        id: agentId,
        kind: 'agent',
        status: 'streaming',
        chips: initialChips(),
        answer: '',
        code: '',
        lowConfidence: false,
      }

      setMessages(prev => [
        ...prev,
        { id: newId('user'), kind: 'user', text: question },
        agentMsg,
      ])
      setInFlight(true)

      try {
        await streamAnalysis(ds.dataset_id, question, {
          onStep: (ev: StepEvent) =>
            patchAgent(agentId, m => ({ ...m, chips: applyStep(m.chips, ev.step, ev.status) })),
          onDone: (ev: DoneEvent) =>
            patchAgent(agentId, m => ({
              ...m,
              status: 'completed',
              chips: m.chips.map(c => (c.status === 'running' || c.status === 'pending' ? { ...c, status: 'done' } : c)),
              answer: ev.answer ?? '',
              code: ev.generated_code ?? '',
              lowConfidence: Boolean(ev.low_confidence),
              lowConfidenceNote: ev.low_confidence_note,
            })),
          onError: (ev: StreamErrorEvent) =>
            patchAgent(agentId, m => ({
              ...m,
              status: 'failed',
              chips: markError(m.chips),
              errorText: ev.message,
            })),
        })
      } catch (err) {
        if (err instanceof NetworkError) {
          handleNetworkError()
          patchAgent(agentId, m => ({
            ...m,
            status: 'failed',
            chips: markError(m.chips),
            errorText: "Can't reach the server. Check it's running on :8001 and try again.",
          }))
        } else {
          const message = err instanceof ApiError ? err.message : 'Something went wrong running the analysis.'
          patchAgent(agentId, m => ({
            ...m,
            status: 'failed',
            chips: markError(m.chips),
            errorText: message,
          }))
        }
      } finally {
        setInFlight(false)
      }
    },
    [inFlight, patchAgent, handleNetworkError],
  )

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <Header />

      <div className="mx-auto flex w-full max-w-6xl flex-1 overflow-hidden">
        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="px-4 pt-4">
            <UploadControl
              onUploading={setUploading}
              onProfile={handleProfile}
              onReject={handleReject}
              onNetworkError={handleNetworkError}
              busy={uploading}
              hasDataset={dataset !== null}
            />
          </div>

          <MessageThread messages={messages} />

          <Composer onSend={question => void handleSend(question)} hasDataset={dataset !== null} inFlight={inFlight} />
        </main>

        <ComingSoonRail />
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
