// Discriminated union of everything that can appear in the chat thread.

import type { DatasetProfile } from './api'
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
}

export type ChatMessage = UserMessage | ProfileMsg | SystemMsg | AgentMessage

let counter = 0
export function newId(prefix: string): string {
  counter += 1
  return `${prefix}-${counter}-${Date.now()}`
}
