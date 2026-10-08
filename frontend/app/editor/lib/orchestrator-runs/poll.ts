'use client'

import { useEffect, useRef, useState } from 'react'

import { getRun } from './api'
import { isTerminal } from './labels'
import type { RunSummary } from './types'

export const POLL_FAST_MS = 1000
export const POLL_MS = 3000
/** How long after submission the fast cadence lasts. */
export const FAST_WINDOW_MS = 20_000

/**
 * A `limits` run lands a step every 1-2 s and ends in ~9 s (measured 2026-10-08: 대지 +3.9, 법규 +6.3,
 * 검토 조정 +7.5), so a 3 s cadence hid most of it. Poll every second at first, every 3 s afterwards.
 */
export const pollInterval = (elapsedMs: number): number => (elapsedMs < FAST_WINDOW_MS ? POLL_FAST_MS : POLL_MS)

/**
 * Follows a submitted run: one timer chain per run, a fresh `GET /runs/{id}` on the cadence of
 * `pollInterval` (or a fixed `intervalMs`) until the status is terminal or the caller unmounts
 * (AbortController). The polled run keeps the submission's `trace_id` (only the POST answer carries
 * it). `stale` is true after a missed poll.
 */
export function useRunPolling(projectId: string | null, run: RunSummary | null, onRun: (run: RunSummary) => void, intervalMs?: number): { stale: boolean } {
  const [stale, setStale] = useState(false)
  // A missed poll bumps this so the effect schedules the next tick although `run` did not change.
  const [misses, setMisses] = useState(0)
  /** When this run was first followed; the cadence counts from here. */
  const followed = useRef<{ run_id: string; at: number } | null>(null)

  useEffect(() => {
    if (!run || !projectId || isTerminal(run.status)) return
    if (followed.current?.run_id !== run.run_id) followed.current = { run_id: run.run_id, at: Date.now() }
    const controller = new AbortController()
    const { run_id, trace_id } = run
    const timer = window.setTimeout(async () => {
      try {
        const next = await getRun(projectId, run_id, controller.signal)
        if (controller.signal.aborted) return
        setStale(false)
        onRun({ ...next, trace_id: next.trace_id ?? trace_id })
      } catch {
        // A missed poll keeps the last known status and tries again next tick.
        if (controller.signal.aborted) return
        setStale(true)
        setMisses((count) => count + 1)
      }
    }, intervalMs ?? pollInterval(Date.now() - followed.current.at))
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [projectId, run, onRun, intervalMs, misses])

  return { stale }
}
