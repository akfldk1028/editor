'use client'

import { useEffect, useMemo, useState } from 'react'

import { getRun } from '@/lib/orchestrator-runs/api'
import { isTerminal } from '@/lib/orchestrator-runs/labels'
import type { Hop, RunSummary } from '@/lib/orchestrator-runs/types'

import type { CollaborationMessage } from '../lib/transcript'
import { toTranscript } from '../lib/transcript'

/** A run whose calls the ledger does not hold yet is read from the Orchestrator's own record and followed while it is open. */
const FOLLOW_MS = 4_000

/**
 * The runs this conversation started (`start_run` rows) whose agent calls the ledger has not received: their
 * Orchestrator records, as messages placed right after the row that started them. Once agents write their calls to
 * the ledger directly, a run's rows arrive by themselves and its record is no longer read.
 */
export function useLinkedRuns(projectId: string | null, hops: readonly Hop[]): CollaborationMessage[] {
  const wanted = useMemo(() => {
    const recorded = new Set(hops.filter((hop) => hop.operation !== 'start_run' && hop.run_id).map((hop) => hop.run_id))
    return hops.filter((hop) => hop.operation === 'start_run' && hop.run_id && !recorded.has(hop.run_id))
      .map((hop) => ({ run_id: hop.run_id as string, at: Date.parse(hop.ts_start) || 0 }))
  }, [hops])
  const key = JSON.stringify(wanted.map((item) => item.run_id))
  const [records, setRecords] = useState<Record<string, RunSummary>>({})
  const [ticks, setTicks] = useState(0)

  useEffect(() => {
    const ids = JSON.parse(key) as string[]
    if (!projectId || !ids.length) return
    const controller = new AbortController()
    let timer: number | null = null
    Promise.all(ids.map((id) => getRun(projectId, id, controller.signal).catch(() => null))).then((list) => {
      if (controller.signal.aborted) return
      setRecords((current) => {
        const next = { ...current }
        let changed = false
        list.forEach((run, index) => {
          const id = ids[index] as string
          if (run && JSON.stringify(current[id]) !== JSON.stringify(run)) { next[id] = run; changed = true }
        })
        return changed ? next : current
      })
      if (list.some((run) => run && !isTerminal(run.status))) timer = window.setTimeout(() => setTicks((count) => count + 1), FOLLOW_MS)
    })
    return () => { controller.abort(); if (timer !== null) window.clearTimeout(timer) }
  }, [projectId, key, ticks])

  return useMemo(() => wanted.flatMap((item) => {
    const run = records[item.run_id]
    return run ? toTranscript(run).messages.map((message, index) => ({ ...message, at: item.at + index + 1 })) : []
  }), [wanted, records])
}
