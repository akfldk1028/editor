'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { listProjects, type ProjectBinding } from '../../../agent-dialogue/projects'
import { getRun, getRunContext, type RunSummary, submitRun } from '../../../agent-dialogue/runs'
import type { SavedSite } from '../lib/picks'
import { describeFailure, idempotencyKey, isTerminal, type ProjectChoice, type RunFailure, resolveProject, siteRunRequest } from '../lib/site-run'

const POLL_MS = 3000

export type RunPhase =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'submitted'; run: RunSummary; stale: boolean }
  | { kind: 'failed'; failure: RunFailure }

export type Projects = { kind: 'loading' } | { kind: 'error'; text: string } | ProjectChoice

/**
 * 검토 시작 for a saved site: pick the project binding, submit `{goal: limits, pnu}` through the
 * editor door with a fresh Idempotency-Key per attempt, then poll the run until it ends or the
 * panel unmounts.
 */
export function useSiteRun(site: SavedSite, projectParam: string | undefined) {
  const [projects, setProjects] = useState<Projects>({ kind: 'loading' })
  const [chosen, setChosen] = useState<ProjectBinding | null>(null)
  const [phase, setPhase] = useState<RunPhase>({ kind: 'idle' })
  const attempts = useRef(0)
  const active = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listProjects(controller.signal)
      .then((bindings) => {
        if (controller.signal.aborted) return
        const choice = resolveProject(bindings, projectParam)
        setProjects(choice)
        setChosen(choice.kind === 'resolved' ? choice.project : null)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProjects({ kind: 'error', text: error instanceof Error ? error.message : '프로젝트 목록을 불러오지 못했어요.' })
      })
    return () => controller.abort()
  }, [projectParam])

  // Polling: one timer chain per submitted run; it stops at a terminal status or when the panel unmounts.
  useEffect(() => {
    if (phase.kind !== 'submitted' || isTerminal(phase.run.status) || !chosen) return
    const controller = new AbortController()
    const { run_id, trace_id } = phase.run
    const timer = window.setTimeout(async () => {
      try {
        const run = await getRun(chosen.project_id, run_id, controller.signal)
        // Only the submission answer carries the trace id; polled runs come from the Orchestrator without it.
        if (!controller.signal.aborted) setPhase({ kind: 'submitted', run: { ...run, trace_id: run.trace_id ?? trace_id }, stale: false })
      } catch {
        // A missed poll keeps the last known status and tries again next tick.
        if (!controller.signal.aborted) setPhase((current) => current.kind === 'submitted' ? { ...current, stale: true } : current)
      }
    }, POLL_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [phase, chosen])

  useEffect(() => () => active.current?.abort(), [])

  const start = useCallback(async () => {
    if (!chosen || phase.kind === 'submitting') return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setPhase({ kind: 'submitting' })
    const key = idempotencyKey(site, ++attempts.current)
    try {
      const context = await getRunContext(chosen.project_id, controller.signal)
      const run = await submitRun(chosen.project_id, context, key, siteRunRequest(site), controller.signal)
      if (!controller.signal.aborted) setPhase({ kind: 'submitted', run, stale: false })
    } catch (error) {
      if (!controller.signal.aborted) setPhase({ kind: 'failed', failure: describeFailure(error) })
    }
  }, [chosen, phase.kind, site])

  return { projects, chosen, setChosen, phase, start }
}
