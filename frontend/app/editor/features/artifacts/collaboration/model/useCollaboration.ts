'use client'

import { useCallback, useEffect, useState } from 'react'

import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import { getRun, listRuns } from '@/lib/orchestrator-runs/api'
import { useRunPolling } from '@/lib/orchestrator-runs/poll'
import type { RunSummary } from '@/lib/orchestrator-runs/types'

export type CollaborationLoad = { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; text: string }

/**
 * The run the 협업 panel shows: `params.run` in `params.project` when the opener named one, else the
 * conversation's project and its newest run (the owner lists newest first). An open run is polled.
 */
export function useCollaboration(params: Readonly<Record<string, string>>) {
  const { projects, chosen, setChosen } = useProjectBinding(params.project)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selected, setSelected] = useState<string | null>(params.run ?? null)
  const [run, setRun] = useState<RunSummary | null>(null)
  const [load, setLoad] = useState<CollaborationLoad>({ kind: 'loading' })
  const [reloads, setReloads] = useState(0)

  useEffect(() => { if (params.run) setSelected(params.run) }, [params.run])

  useEffect(() => {
    if (!chosen) return
    const controller = new AbortController()
    setLoad({ kind: 'loading' })
    listRuns(chosen.project_id, controller.signal)
      .then(async (list) => {
        if (controller.signal.aborted) return
        setRuns(list)
        const id = selected && list.some((item) => item.run_id === selected) ? selected : list[0]?.run_id ?? null
        const detail = id ? await getRun(chosen.project_id, id, controller.signal) : null
        if (controller.signal.aborted) return
        setRun(detail)
        if (id !== selected) setSelected(id)
        setLoad({ kind: 'ready' })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoad({ kind: 'error', text: error instanceof Error ? error.message : '실행 기록을 불러오지 못했어요.' })
      })
    return () => controller.abort()
  }, [chosen, selected, reloads])

  const onRun = useCallback((next: RunSummary) => setRun(next), [])
  const { stale } = useRunPolling(chosen?.project_id ?? null, run, onRun)
  const reload = useCallback(() => setReloads((count) => count + 1), [])

  return { projects, chosen, setChosen, runs, run, selected, select: setSelected, load, stale, reload }
}
