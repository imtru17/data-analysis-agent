'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  streamAnalysis,
  fetchTodayCost,
  fetchRun,
  NetworkError,
  ApiError,
  type Connection,
  type DatasetProfile,
  type SessionDetail,
  type SessionSummary,
  type Source,
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
import { SourcePanel } from './components/SourcePanel'
import { ConnectDb } from './components/ConnectDb'
import { SessionBrowser } from './components/SessionBrowser'
import { Toast } from './components/Toast'

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState(false)
  const [inFlight, setInFlight] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [wantChart, setWantChart] = useState(false)
  const [todayCost, setTodayCost] = useState<number | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const [connectOpen, setConnectOpen] = useState(false)

  const sourcesRef = useRef<Source[]>([])
  const selectedRef = useRef<Set<string>>(new Set())
  const sessionIdRef = useRef<string | null>(null)
  const wantChartRef = useRef(false)
  const uploadOpenRef = useRef<(() => void) | null>(null)

  const refreshTodayCost = useCallback(async () => {
    const cost = await fetchTodayCost()
    if (cost) setTodayCost(cost.cost_usd)
  }, [])

  useEffect(() => {
    void refreshTodayCost()
  }, [refreshTodayCost])

  const patchAgent = useCallback((id: string, patch: (m: AgentMessage) => AgentMessage) => {
    setMessages(prev =>
      prev.map(m => (m.id === id && m.kind === 'agent' ? patch(m) : m)),
    )
  }, [])

  const setSourcesBoth = useCallback((next: Source[]) => {
    sourcesRef.current = next
    setSources(next)
  }, [])

  const setSelectedBoth = useCallback((next: Set<string>) => {
    selectedRef.current = next
    setSelectedSourceIds(next)
  }, [])

  const addSource = useCallback(
    (source: Source) => {
      const next = [...sourcesRef.current.filter(s => s.id !== source.id), source]
      setSourcesBoth(next)
      const sel = new Set(selectedRef.current)
      sel.add(source.id)
      setSelectedBoth(sel)
    },
    [setSourcesBoth, setSelectedBoth],
  )

  const handleProfile = useCallback(
    (profile: DatasetProfile) => {
      addSource({
        id: profile.dataset_id,
        kind: 'file',
        name: profile.filename,
        detail: `${profile.row_count.toLocaleString()} rows · ${profile.columns.length} cols`,
      })
      setMessages(prev => [...prev, { id: newId('profile'), kind: 'profile', profile }])
    },
    [addSource],
  )

  const handleConnected = useCallback(
    (conn: Connection) => {
      addSource({
        id: conn.connection_id,
        kind: 'db',
        name: conn.name,
        detail: conn.dsn_masked,
      })
      const tableCount = conn.tables?.length ?? 0
      setMessages(prev => [
        ...prev,
        {
          id: newId('sys'),
          kind: 'system',
          tone: 'info',
          text: `Connected "${conn.name}" (${conn.kind}) · ${conn.dsn_masked}${
            tableCount ? ` · ${tableCount} table${tableCount === 1 ? '' : 's'}` : ''
          }.`,
        },
      ])
    },
    [addSource],
  )

  const handleReject = useCallback((text: string) => {
    setMessages(prev => [...prev, { id: newId('sys'), kind: 'system', text, tone: 'error' }])
  }, [])

  const handleNetworkError = useCallback(() => {
    setToast("Can't reach the server — is it running on :8001?")
  }, [])

  const setChartToggle = useCallback((on: boolean) => {
    setWantChart(on)
    wantChartRef.current = on
  }, [])

  const toggleSelectSource = useCallback(
    (id: string) => {
      const next = new Set(selectedRef.current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      setSelectedBoth(next)
    },
    [setSelectedBoth],
  )

  const handleSend = useCallback(
    async (question: string, chart: boolean) => {
      const src = sourcesRef.current
      const selected = selectedRef.current
      const chosenIds =
        selected.size > 0 ? src.filter(s => selected.has(s.id)).map(s => s.id) : src.map(s => s.id)
      if (chosenIds.length === 0 || inFlight) return

      // The backend keeps `dataset_id` as the single-source primary; prefer a file
      // source, otherwise fall back to the first chosen source.
      const fileFirst = src.find(s => chosenIds.includes(s.id) && s.kind === 'file')
      const primaryId = fileFirst?.id ?? chosenIds[0]

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
        await streamAnalysis(
          primaryId,
          question,
          {
            onStep: (ev: StepEvent) =>
              patchAgent(agentId, m => ({ ...m, chips: applyStep(m.chips, ev.step, ev.status) })),
            onDone: (ev: DoneEvent) => {
              patchAgent(agentId, m => ({
                ...m,
                status: 'completed',
                chips: m.chips.map(c =>
                  c.status === 'running' || c.status === 'pending' ? { ...c, status: 'done' } : c,
                ),
                answer: ev.answer ?? '',
                code: ev.generated_code ?? '',
                lowConfidence: Boolean(ev.low_confidence),
                lowConfidenceNote: ev.low_confidence_note,
                runId: ev.run_id,
                tokens: ev.tokens,
                costUsd: ev.cost_usd,
                chartSpec: ev.chart_spec ?? null,
              }))
              void refreshTodayCost()
            },
            onError: (ev: StreamErrorEvent) =>
              patchAgent(agentId, m => ({
                ...m,
                status: 'failed',
                chips: markError(m.chips),
                errorText: ev.message,
              })),
          },
          {
            want_chart: chart,
            source_ids: chosenIds,
            session_id: sessionIdRef.current ?? undefined,
          },
        )
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
    [inFlight, patchAgent, handleNetworkError, refreshTodayCost],
  )

  const handleFollowup = useCallback(
    (question: string) => {
      if (sourcesRef.current.length === 0 || inFlight) return
      setDraft(question)
      void handleSend(question, wantChartRef.current)
      setDraft('')
    },
    [inFlight, handleSend],
  )

  const openUpload = useCallback(() => {
    uploadOpenRef.current?.()
  }, [])

  const handleNewSession = useCallback((session: SessionSummary) => {
    sessionIdRef.current = session.session_id
    setSessionId(session.session_id)
    // A fresh session starts an empty workspace.
    setMessages([])
    setSourcesBoth([])
    setSelectedBoth(new Set())
  }, [setSourcesBoth, setSelectedBoth])

  const handleRestoreSession = useCallback(
    async (detail: SessionDetail) => {
      const newSources: Source[] = []
      const annByDataset = new Map<string, Record<string, string>>()
      for (const a of detail.annotations ?? []) {
        if (!a.table_name) {
          const m = annByDataset.get(a.source_id) ?? {}
          m[a.column] = a.note
          annByDataset.set(a.source_id, m)
        }
      }

      const restored: ChatMessage[] = []

      for (const ds of detail.datasets ?? []) {
        newSources.push({
          id: ds.dataset_id,
          kind: 'file',
          name: ds.filename,
          detail: `${(ds.row_count ?? 0).toLocaleString()} rows · ${ds.columns?.length ?? 0} cols`,
        })
        if (ds.columns && ds.columns.length > 0) {
          restored.push({
            id: newId('profile'),
            kind: 'profile',
            profile: ds,
            annotations: annByDataset.get(ds.dataset_id),
          })
        }
      }

      for (const c of detail.connections ?? []) {
        newSources.push({ id: c.connection_id, kind: 'db', name: c.name, detail: c.dsn_masked })
      }

      const msgs = detail.messages ?? []
      const runDetails = await Promise.all(
        msgs.map(m => (m.role !== 'user' && m.run_id ? fetchRun(m.run_id) : Promise.resolve(null))),
      )

      msgs.forEach((m, i) => {
        if (m.role === 'user') {
          restored.push({ id: newId('user'), kind: 'user', text: m.content })
        } else {
          const run = runDetails[i]
          restored.push({
            id: newId('agent'),
            kind: 'agent',
            status: 'completed',
            chips: initialChips().map(c => ({ ...c, status: 'done' as const })),
            answer: m.content || run?.answer || '',
            code: run?.generated_code ?? '',
            lowConfidence: Boolean(run?.low_confidence),
            runId: m.run_id ?? run?.run_id,
            tokens: run?.tokens,
            costUsd: run?.cost_usd,
            chartSpec: run?.chart_spec ?? null,
          })
        }
      })

      setMessages(restored)
      setSourcesBoth(newSources)
      setSelectedBoth(new Set(newSources.map(s => s.id)))
      sessionIdRef.current = detail.session_id
      setSessionId(detail.session_id)
    },
    [setSourcesBoth, setSelectedBoth],
  )

  const hasSources = sources.length > 0

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <Header
        todayCost={todayCost}
        sessionsOpen={sessionsOpen}
        onToggleSessions={() => setSessionsOpen(v => !v)}
        sessionsPanel={
          <SessionBrowser
            open={sessionsOpen}
            onClose={() => setSessionsOpen(false)}
            currentSessionId={sessionId}
            onRestore={detail => void handleRestoreSession(detail)}
            onNewSession={handleNewSession}
            onNetworkError={handleNetworkError}
          />
        }
      />

      <div className="mx-auto flex w-full max-w-6xl flex-1 overflow-hidden">
        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="px-4 pt-4">
            <UploadControl
              onUploading={setUploading}
              onProfile={handleProfile}
              onReject={handleReject}
              onNetworkError={handleNetworkError}
              busy={uploading}
              hasDataset={hasSources}
              onReady={fn => {
                uploadOpenRef.current = fn
              }}
            />
          </div>

          <MessageThread
            messages={messages}
            onFollowup={handleFollowup}
            followupsDisabled={inFlight}
            onNetworkError={handleNetworkError}
          />

          <Composer
            value={draft}
            onValueChange={setDraft}
            onSend={(question, chart) => void handleSend(question, chart)}
            hasDataset={hasSources}
            inFlight={inFlight}
            wantChart={wantChart}
            onToggleChart={setChartToggle}
          />
        </main>

        <SourcePanel
          sources={sources}
          selectedIds={selectedSourceIds}
          onToggleSelect={toggleSelectSource}
          onUploadClick={openUpload}
          onConnectDb={() => setConnectOpen(true)}
        />
      </div>

      <ConnectDb
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={handleConnected}
        onNetworkError={handleNetworkError}
        sessionId={sessionId}
      />

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
