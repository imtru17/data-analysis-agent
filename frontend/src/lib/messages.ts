// Discriminated union of everything that can appear in the chat thread.

import type { ChartSpec, DatasetProfile, Tokens } from './api'
import type { StepChip } from './steps'

export interface UserMessage {
  id: string
  kind: 'user'
  text: string
}

export interface ProfileMsg {
  id: string
  kind: 'profile'
  profile: DatasetProfile
  /** Phase-3: restored column annotations, keyed by column name. */
  annotations?: Record<string, string>
}

export interface SystemMsg {
  id: string
  kind: 'system'
  text: string
  tone: 'error' | 'info'
}

export type AgentStatus = 'streaming' | 'completed' | 'failed'

export interface AgentMessage {
  id: string
  kind: 'agent'
  status: AgentStatus
  chips: StepChip[]
  answer: string
  code: string
  lowConfidence: boolean
  lowConfidenceNote?: string
  errorText?: string
  /** Phase-2: the run id (for exports), token/cost accounting, and chart spec. */
  runId?: string
  tokens?: Tokens
  costUsd?: number
  chartSpec?: ChartSpec | null
}

export type ChatMessage = UserMessage | ProfileMsg | SystemMsg | AgentMessage

let counter = 0
export function newId(prefix: string): string {
  counter += 1
  return `${prefix}-${counter}-${Date.now()}`
}
