'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { getRunContext, listProjects, submitRun } from '@/lib/orchestrator-runs/api'
import { defaultRunConditions, isValidDate, loadRunConditions, type RunConditions, saveRunConditions } from '@/lib/orchestrator-runs/conditions'
import { useRunPolling } from '@/lib/orchestrator-runs/poll'
import { describeFailure, type ProjectChoice, resolveProject, type RunFailure } from '@/lib/orchestrator-runs/submit'
import type { ProjectBinding, RunSummary } from '@/lib/orchestrator-runs/types'
import { useRunFeed } from '@/lib/orchestrator-runs/useRunFeed'

import type { SavedSite } from '../lib/picks'
import { idempotencyKey, siteRunRequest } from '../lib/site-run'

export type RunPhase =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'submitted'; run: RunSummary; stale: boolean }
  | { kind: 'failed'; failure: RunFailure }

export type Projects = { kind: 'loading' } | { kind: 'error'; text: string } | ProjectChoice

/**
 * 검토 시작 for a saved site: pick the project binding and the 조건 (기준일, 용도), submit
 * `{goal: limits, pnu, parcels, assessment_date, building_type?}` through the editor door with a
 * fresh Idempotency-Key per attempt, then follow the run (shared poller) until it ends or the panel
 * unmounts; every step reaches the conversation feed once.
 */
export function useSiteRun(site: SavedSite, projectParam: string | undefined) {
  const [projects, setProjects] = useState<Projects>({ kind: 'loading' })
  const [chosen, setChosen] = useState<ProjectBinding | null>(null)
  const [conditions, setConditions] = useState<RunConditions>(defaultRunConditions)
  const [state, setState] = useState<Exclude<RunPhase, { kind: 'submitted' }> | { kind: 'submitted'; run: RunSummary }>({ kind: 'idle' })
  // Attempts count from a per-mount nonce: after a reload the same selection must not reuse a key whose
  // run already moved the source versions (the Orchestrator answers 409 to a replay with a changed body).
  const attempts = useRef(Math.floor(Date.now() / 1000) % 1_000_000)
  const active = useRef<AbortController | null>(null)
  const ready = isValidDate(conditions.assessmentDate)

  // The last used 조건 come from localStorage after mount, so the server and first client render agree.
  useEffect(() => setConditions(loadRunConditions()), [])

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

  const run = state.kind === 'submitted' ? state.run : null
  const onRun = useCallback((next: RunSummary) => setState({ kind: 'submitted', run: next }), [])
  const { stale } = useRunPolling(chosen?.project_id ?? null, run, onRun)
  const first = site.parcels[0]!
  // 법규 결과 보기 opens the law artifact under the binding this run went to, so it finds the same run.
  useRunFeed(run, { projectId: chosen?.project_id ?? null, pnu: first.pnu, address: first.address || site.label, project: projectParam ?? chosen?.project_id })

  useEffect(() => () => active.current?.abort(), [])

  const start = useCallback(async () => {
    if (!chosen || !ready || state.kind === 'submitting') return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setState({ kind: 'submitting' })
    saveRunConditions(conditions)
    const key = idempotencyKey(site, ++attempts.current)
    try {
      const context = await getRunContext(chosen.project_id, controller.signal)
      const submitted = await submitRun(chosen.project_id, context, key, siteRunRequest(site, conditions), controller.signal)
      if (!controller.signal.aborted) setState({ kind: 'submitted', run: submitted })
    } catch (error) {
      if (!controller.signal.aborted) setState({ kind: 'failed', failure: describeFailure(error) })
    }
  }, [chosen, conditions, state.kind, ready, site])

  const phase: RunPhase = state.kind === 'submitted' ? { kind: 'submitted', run: state.run, stale } : state
  return { projects, chosen, setChosen, conditions, setConditions, ready, phase, start }
}
