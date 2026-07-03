// Canonical ordered step pipeline shown as live chips. Backend node names map
// to the human labels the user sees. Keeping this list here lets the UI render
// all chips up-front and flip each one as `step` SSE events arrive.

export type ChipStatus = 'pending' | 'running' | 'done' | 'skipped' | 'error'

export interface StepChip {
  key: string
  label: string
  status: ChipStatus
}

export const STEP_ORDER: { key: string; label: string }[] = [
  { key: 'plan', label: 'Planning' },
  { key: 'generate_code', label: 'Writing code' },
  { key: 'execute_locally', label: 'Running locally' },
  { key: 'verify', label: 'Verifying' },
  { key: 'answer', label: 'Answering' },
]

export function initialChips(): StepChip[] {
  return STEP_ORDER.map(s => ({ key: s.key, label: s.label, status: 'pending' as ChipStatus }))
}

/**
 * Apply an incoming step event to the chip list. Any earlier chips still pending
 * when a later chip becomes active are marked `skipped` (this renders the
 * fast-path "Planning skipped" behaviour even if the backend omits the event).
 */
export function applyStep(
  chips: StepChip[],
  stepKey: string,
  status: string,
): StepChip[] {
  const idx = chips.findIndex(c => c.key === stepKey)
  if (idx === -1) return chips
  const next = chips.map(c => ({ ...c }))
  const mapped: ChipStatus =
    status === 'running' ? 'running' : status === 'skipped' ? 'skipped' : 'done'
  next[idx].status = mapped
  for (let i = 0; i < idx; i++) {
    if (next[i].status === 'pending') next[i].status = 'skipped'
  }
  return next
}

/** Mark the active (running) chip — or the first pending one — as errored. */
export function markError(chips: StepChip[]): StepChip[] {
  const next = chips.map(c => ({ ...c }))
  let target = next.findIndex(c => c.status === 'running')
  if (target === -1) target = next.findIndex(c => c.status === 'pending')
  if (target !== -1) next[target].status = 'error'
  return next
}
