'use client'

import type { Tokens } from '@/lib/api'

// Real per-answer token + cost badge (replaces the Phase-1 "tokens/cost —" stub).
// Values come straight from the SSE `done` payload's `tokens` + `cost_usd`.

export function CostBadge({ tokens, costUsd }: { tokens?: Tokens; costUsd?: number }) {
  const total = tokens ? tokens.prompt + tokens.completion : undefined
  const cost = typeof costUsd === 'number' ? costUsd : undefined

  return (
    <span
      data-testid="cost-badge"
      title={
        tokens
          ? `${tokens.prompt.toLocaleString()} prompt + ${tokens.completion.toLocaleString()} completion tokens`
          : undefined
      }
      className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-600"
    >
      {total !== undefined && <span>{total.toLocaleString()} tokens</span>}
      {total !== undefined && cost !== undefined && <span className="text-gray-300">·</span>}
      {cost !== undefined && <span>{formatCost(cost)}</span>}
    </span>
  )
}

function formatCost(value: number): string {
  // Sub-cent runs are common; show up to 4 dp so a real number always appears.
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}
