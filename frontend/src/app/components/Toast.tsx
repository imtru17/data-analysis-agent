'use client'

import { useEffect } from 'react'

// A transient error toast, used for network-reachability failures.

export function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 6000)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div
      role="alert"
      data-testid="toast"
      className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-red-200 bg-red-600 px-4 py-2.5 text-sm font-medium text-white shadow-lg"
    >
      <div className="flex items-center gap-3">
        <span>{message}</span>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="rounded px-1 text-white/80 hover:text-white"
        >
          ✕
        </button>
      </div>
    </div>
  )
}
