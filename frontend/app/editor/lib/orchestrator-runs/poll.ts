'use client'

import { useEffect, useState } from 'react'

import { getRun } from './api'
import { isTerminal } from './labels'
import type { RunSummary } from './types'

export const POLL_MS = 3000

/**
 * Follows a submitted run: one timer chain per run, a fresh `GET /runs/{id}` every `intervalMs`
 * until the status is terminal or the caller unmounts (AbortController). The polled run keeps the
 * submission's `trace_id` (only the POST answer carries it). `stale` is true after a missed poll.
 */
export function useRunPolling(projectId: string | null, run: RunSummary | null, onRun: (run: RunSummary) => void, intervalMs = POLL_MS): { stale: boolean } {
  const [stale, setStale] = useState(false)
  // A missed poll bumps this so the effect schedules the next tick although `run` did not change.
  const [misses, setMisses] = useState(0)

  useEffect(() => {
    if (!run || !projectId || isTerminal(run.status)) return
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
    }, intervalMs)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [projectId, run, onRun, intervalMs, misses])

  return { stale }
}
