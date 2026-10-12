'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { getRunContext, submitHealth } from '@/lib/orchestrator-runs/api'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'

import { clearPendingHealth, type PendingHealth, readPendingHealth, savePendingHealth } from '../lib/pending-health'

export type HealthRunState = { kind: 'idle' } | { kind: 'busy' } | { kind: 'done'; runId: string } | { kind: 'error'; text: string }

/**
 * 연결 점검: a `health` run for the project, which makes the Orchestrator call every agent once. An
 * attempt whose answer was lost is kept in sessionStorage and replayed with the same key, never doubled.
 */
export function useHealthRun(project: ProjectBinding | null) {
  const [state, setState] = useState<HealthRunState>({ kind: 'idle' })
  const [retrying, setRetrying] = useState(false)
  const pending = useRef<AbortController | null>(null)
  const attempt = useRef<PendingHealth | null>(null)

  useEffect(() => {
    attempt.current = null
    setState({ kind: 'idle' })
    if (!project) return
    try {
      attempt.current = readPendingHealth(sessionStorage, project.project_id)
      setRetrying(attempt.current !== null)
    } catch (error) { setState({ kind: 'error', text: error instanceof Error ? error.message : '이전 요청 복원 실패' }) }
    return () => pending.current?.abort()
  }, [project])

  const submit = useCallback(async () => {
    if (!project || pending.current) return
    const controller = new AbortController()
    pending.current = controller
    setState({ kind: 'busy' })
    try {
      if (!attempt.current) attempt.current = { key: crypto.randomUUID(), context: await getRunContext(project.project_id, controller.signal) }
      savePendingHealth(sessionStorage, project.project_id, attempt.current)
      const run = await submitHealth(project.project_id, attempt.current.context, attempt.current.key, controller.signal)
      if (run.owner_project_id !== project.owner_project_id || run.branch_id !== project.branch_id || run.request_id !== `editor:${project.project_id}:${attempt.current.key}`) {
        throw new Error('접수된 실행의 프로젝트·요청 연결이 일치하지 않아요.')
      }
      if (controller.signal.aborted) return
      clearPendingHealth(sessionStorage, project.project_id)
      attempt.current = null
      setRetrying(false)
      setState({ kind: 'done', runId: run.run_id })
    } catch (error) {
      if (controller.signal.aborted) return
      setRetrying(attempt.current !== null)
      setState({ kind: 'error', text: error instanceof Error ? error.message : '실행 요청 실패' })
    } finally {
      pending.current = null
    }
  }, [project])

  return { state, retrying, submit }
}
