'use client'

import { useEffect, useState } from 'react'

import { listRuns } from '@/lib/orchestrator-runs/api'
import type { RunQuestion } from '@/lib/orchestrator-runs/types'

/** How often a workspace's runs are read again while a conversation shows it. */
const POLL_MS = 10_000

export interface WaitingQuestion {
  runId: string
  question: RunQuestion
}

/**
 * The questions runs of this workspace wait on (a district lot, a building type, a parking count, an intent to
 * reconfirm), answered here: whichever way a run was started - from the map, the law panel or by the Orchestrator
 * for this workspace - its question reaches the conversation. Read again every few seconds while shown; an answered run leaves the list when it moves on.
 */
export function useWaitingQuestions(projectId: string | null): WaitingQuestion[] {
  const [waiting, setWaiting] = useState<WaitingQuestion[]>([])
  useEffect(() => {
    setWaiting([])
    if (!projectId) return
    const controller = new AbortController()
    let timer = 0
    const read = () => {
      listRuns(projectId, controller.signal).then((runs) => {
        if (controller.signal.aborted) return
        setWaiting(runs.filter((run) => run.status === 'waiting_input' && !!run.pending_request && Array.isArray(run.pending_request.fields))
          .map((run) => ({ runId: run.run_id, question: run.pending_request as RunQuestion })))
      }).catch(() => undefined).finally(() => {
        if (!controller.signal.aborted) timer = window.setTimeout(read, POLL_MS)
      })
    }
    read()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [projectId])
  return waiting
}
