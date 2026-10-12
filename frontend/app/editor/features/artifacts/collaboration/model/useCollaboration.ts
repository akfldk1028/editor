'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import { loadCapabilities } from '@/lib/goals'
import { getRun, listRuns } from '@/lib/orchestrator-runs/api'
import { useRunPolling } from '@/lib/orchestrator-runs/poll'
import type { RunSummary } from '@/lib/orchestrator-runs/types'

export type CollaborationLoad = { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; text: string }

/**
 * The run the 협업 panel shows: `params.run` in `params.project` when the opener named one, else the
 * conversation's project and its newest run (the owner lists newest first). The list is read once per project
 * (and on 다시 확인); the chosen run is read on its own and polled while open, and the list row follows it.
 */
export function useCollaboration(params: Readonly<Record<string, string>>) {
  const { projects, chosen, setChosen } = useProjectBinding(params.project)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [picked, setPicked] = useState<string | null>(params.run ?? null)
  const [run, setRun] = useState<RunSummary | null>(null)
  const [load, setLoad] = useState<CollaborationLoad>({ kind: 'loading' })
  const [reloads, setReloads] = useState(0)
  const [goals, setGoals] = useState<Record<string, string>>({})

  useEffect(() => { if (params.run) setPicked(params.run) }, [params.run])

  // Goal labels in the user's words come from the Orchestrator's catalog, not from a table here.
  useEffect(() => {
    const controller = new AbortController()
    loadCapabilities(controller.signal)
      .then((capabilities) => { if (!controller.signal.aborted) setGoals(Object.fromEntries(capabilities.goals.map((goal) => [goal.id, goal.label]))) })
      .catch(() => undefined)
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!chosen) return
    const controller = new AbortController()
    setLoad({ kind: 'loading' })
    listRuns(chosen.project_id, controller.signal)
      .then((list) => { if (!controller.signal.aborted) { setRuns(list); setLoad({ kind: 'ready' }) } })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoad({ kind: 'error', text: error instanceof Error ? error.message : '실행 기록을 불러오지 못했어요.' })
      })
    return () => controller.abort()
  }, [chosen, reloads])

  const selected = useMemo(() => (picked && runs.some((item) => item.run_id === picked) ? picked : runs[0]?.run_id ?? null), [picked, runs])

  useEffect(() => {
    if (!chosen || !selected) { setRun(null); return }
    const controller = new AbortController()
    getRun(chosen.project_id, selected, controller.signal)
      .then((detail) => { if (!controller.signal.aborted) setRun(detail) })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoad({ kind: 'error', text: error instanceof Error ? error.message : '실행을 불러오지 못했어요.' })
      })
    return () => controller.abort()
  }, [chosen, selected, reloads])

  const onRun = useCallback((next: RunSummary) => {
    setRun(next)
    setRuns((current) => current.map((item) => (item.run_id === next.run_id ? { ...item, status: next.status, pending_input: next.pending_input } : item)))
  }, [])
  const { stale } = useRunPolling(chosen?.project_id ?? null, run, onRun)
  const reload = useCallback(() => setReloads((count) => count + 1), [])

  return { projects, chosen, setChosen, runs, run, selected, select: setPicked, load, stale, reload, goals }
}
