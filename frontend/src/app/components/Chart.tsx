'use client'

import { useEffect, useRef, useState } from 'react'
import type { ChartSpec } from '@/lib/api'

// Renders a Vega-Lite v5 chart spec below an answer using vega-embed. The chart
// is interactive/zoomable (vega-embed's actions menu exposes pan/zoom + source),
// and we add explicit Download PNG / SVG buttons driven by the live Vega view's
// `toImageURL`. vega-embed is imported dynamically inside the effect so nothing
// touches `window`/`document` during the static-export build.

// Minimal structural type for the Vega view we rely on (avoids importing types).
interface VegaView {
  toImageURL(type: 'png' | 'svg', scaleFactor?: number): Promise<string>
  finalize(): void
}

export function Chart({ spec, filenameBase = 'chart' }: { spec: ChartSpec; filenameBase?: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<VegaView | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const el = containerRef.current
    if (!el) return

    setReady(false)
    setError(null)

    ;(async () => {
      try {
        const { default: embed } = await import('vega-embed')
        if (cancelled || !containerRef.current) return
        const result = await embed(containerRef.current, spec as object, {
          actions: { export: true, source: true, compiled: false, editor: false },
          renderer: 'svg',
        })
        if (cancelled) {
          result.view.finalize()
          return
        }
        viewRef.current = result.view as unknown as VegaView
        setReady(true)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not render the chart.')
        }
      }
    })()

    return () => {
      cancelled = true
      if (viewRef.current) {
        viewRef.current.finalize()
        viewRef.current = null
      }
      if (el) el.innerHTML = ''
    }
  }, [spec])

  async function download(type: 'png' | 'svg') {
    const view = viewRef.current
    if (!view) return
    try {
      const url = await view.toImageURL(type, type === 'png' ? 2 : 1)
      const a = document.createElement('a')
      a.href = url
      a.download = `${filenameBase}.${type}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      if (type === 'png') URL.revokeObjectURL(url)
    } catch {
      // best-effort download; nothing to surface if the browser blocks it
    }
  }

  return (
    <div
      data-testid="chart"
      className="mt-3 rounded-lg border border-gray-200 bg-white p-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Chart</span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            data-testid="chart-download-png"
            onClick={() => void download('png')}
            disabled={!ready}
            className="rounded-md border border-gray-200 px-2 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Download PNG
          </button>
          <button
            type="button"
            data-testid="chart-download-svg"
            onClick={() => void download('svg')}
            disabled={!ready}
            className="rounded-md border border-gray-200 px-2 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Download SVG
          </button>
        </div>
      </div>

      <div ref={containerRef} className="overflow-x-auto" data-testid="chart-canvas" />

      {!ready && !error && (
        <p className="text-xs text-gray-400" data-testid="chart-loading">
          Rendering chart…
        </p>
      )}
      {error && (
        <p className="text-xs text-red-500" data-testid="chart-error">
          Couldn&apos;t render the chart: {error}
        </p>
      )}
    </div>
  )
}
