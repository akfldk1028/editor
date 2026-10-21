'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import { useScopedState } from '@/lib/design-conversation/useScopedState'
import { rememberConversationSite } from '@/lib/design-conversation/context'

import { availableGoal, loadCapabilities } from '@/lib/goals'
import { hostStatus, neededAgents, RUN_LEASE_S } from '@/lib/goals/activation'
import { ensureAgents, getRunContext, submitRun } from '@/lib/orchestrator-runs/api'
import { defaultRunConditions, isValidDate, loadRunConditions, type RunConditions, saveRunConditions } from '@/lib/orchestrator-runs/conditions'
import { onCommand } from '@/lib/orchestrator-runs/commands'
import { dismissFeed, postFeed, projectFeed } from '@/lib/orchestrator-runs/feed'
import { activatingLine, activationFailedLine, requestFailedLine, requestingLines } from '@/lib/orchestrator-runs/feed-lines'
import { useRunPolling } from '@/lib/orchestrator-runs/poll'
import { describeFailure, type ProjectChoice, type RunFailure } from '@/lib/orchestrator-runs/submit'
import type { RunSummary } from '@/lib/orchestrator-runs/types'
import { useRunFeed } from '@/lib/orchestrator-runs/useRunFeed'

import type { SavedSite } from '../lib/picks'
import { idempotencyKey, type LayoutInputs, layoutBlocker, layoutRunRequest, loadLayoutInputs, massRunRequest, siteRunRequest } from '../lib/site-run'

export type RunPhase =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'submitted'; run: RunSummary; stale: boolean }
  | { kind: 'failed'; failure: RunFailure }

export type Projects = { kind: 'loading' } | { kind: 'error'; text: string } | ProjectChoice

/** The goals the site card submits: 법규·한계 검토 (`siteRunRequest`), 배치 설계 (`layoutRunRequest`) and 매스 설계 (`massRunRequest`). */
const SITE_GOAL = 'limits'
const LAYOUT_GOAL = 'masterplan'
const MASS_GOAL = 'mass'
export type SiteGoal = typeof SITE_GOAL | typeof LAYOUT_GOAL | typeof MASS_GOAL
const DESIGN_GOALS: readonly string[] = [LAYOUT_GOAL, MASS_GOAL]
/** The window event a finished (or newly submitted) site run announces, so the 3D view fetches the newest layout. */
export const SITE_RUN_EVENT = 'ace:site-run'

/**
 * 검토 시작 for a saved site: pick the project binding and the 조건 (기준일, 용도), submit
 * `{goal: limits, pnu, parcels, assessment_date, building_type?}` through the editor door with a
 * fresh Idempotency-Key per attempt, then follow the run (shared poller) until it ends or the panel
 * unmounts; every step reaches the conversation feed once.
 */
export function useSiteRun(site: SavedSite, projectParam: string | undefined) {
  const { projects, chosen, setChosen, conversationId } = useProjectBinding(projectParam)
  const scope = JSON.stringify([chosen?.project_id, conversationId, site.parcels.map((parcel) => parcel.pnu)])
  const [conditions, setConditions] = useState<RunConditions>(defaultRunConditions)
  const [state, setState] = useScopedState<Exclude<RunPhase, { kind: 'submitted' }> | { kind: 'submitted'; run: RunSummary }>(scope, { kind: 'idle' })
  // Attempts count from a per-mount nonce: after a reload the same selection must not reuse a key whose
  // run already moved the source versions (the Orchestrator answers 409 to a replay with a changed body).
  const attempts = useRef(Math.floor(Date.now() / 1000) % 1_000_000)
  const active = useRef<AbortController | null>(null)
  const ready = isValidDate(conditions.assessmentDate)

  // The last used 조건 come from localStorage after mount, so the server and first client render agree.
  useEffect(() => setConditions(loadRunConditions()), [])

  // Warm the scene route the backend checks on submission (`/api/scenes/{id}`): the dev server compiles it lazily
  // (8-9 s on the first hit), so touching it while the user fills the conditions keeps the first click fast.
  useEffect(() => {
    if (!chosen) return
    const controller = new AbortController()
    void fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/scenes/${encodeURIComponent(chosen.scene_id)}`, { signal: controller.signal }).catch(() => undefined)
    return () => controller.abort()
  }, [chosen])

  const run = state.kind === 'submitted' ? state.run : null
  const onRun = useCallback((next: RunSummary) => {
    setState({ kind: 'submitted', run: next })
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(SITE_RUN_EVENT, { detail: { run_id: next.run_id, goal: next.goal, status: next.status } }))
  }, [setState])
  const { stale } = useRunPolling(chosen?.project_id ?? null, run, onRun)
  const first = site.parcels[0]!
  const siteOwner = useRef<{ pnu: string; projectId: string } | null>(null)
  useEffect(() => {
    if (!chosen) return
    if (!siteOwner.current || siteOwner.current.pnu !== first.pnu) siteOwner.current = { pnu: first.pnu, projectId: chosen.project_id }
    if (siteOwner.current.projectId === chosen.project_id) rememberConversationSite(chosen.project_id, { pnu: first.pnu, address: first.address || site.label }, conditions.assessmentDate)
  }, [chosen, first.pnu, first.address, site.label, conditions.assessmentDate])
  // 법규 결과 보기 opens the law artifact under the binding this run went to, so it finds the same run.
  useRunFeed(run, { projectId: chosen?.project_id ?? null, conversationId, pnu: first.pnu, address: first.address || site.label, project: chosen?.project_id })

  useEffect(() => () => active.current?.abort(), [scope])

  const start = useCallback(async (goal: SiteGoal = SITE_GOAL, layout?: LayoutInputs) => {
    if (!chosen || !ready || state.kind === 'submitting') return
    if (DESIGN_GOALS.includes(goal) && (!layout || layoutBlocker(conditions, layout))) return
    const postFeed = projectFeed(chosen.project_id)
    rememberConversationSite(chosen.project_id, { pnu: site.parcels[0]!.pnu, address: site.parcels[0]!.address || site.label }, conditions.assessmentDate)
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setState({ kind: 'submitting' })
    saveRunConditions(conditions)
    // The conversation answers the click at once; the receipt line follows when the Orchestrator accepts.
    const [bubble, busy] = requestingLines(site.label, conditions)
    postFeed(bubble!)
    let pending = postFeed(busy!)
    const key = idempotencyKey(site, ++attempts.current)
    try {
      // Activation at the call: owners the host has not got up are woken (parallel, dependency-ordered)
      // and the request waits for their health; one that never comes up stops the submission (fail closed).
      const capability = availableGoal(await loadCapabilities(controller.signal), goal)
      const needed = capability ? neededAgents(capability, await hostStatus(controller.signal)) : []
      if (needed.length) {
        if (pending) dismissFeed(pending.id)
        pending = postFeed(activatingLine(needed))
        const woken = await ensureAgents(needed, RUN_LEASE_S, controller.signal)
        if (controller.signal.aborted) return
        if (woken.failed.length) {
          postFeed(activationFailedLine(woken.failed, { kind: 'start-review', goal }))
          setState({ kind: 'failed', failure: { kind: 'rejected', text: `${woken.failed.map((f) => f.agent).join(', ')} 켜기 실패` } })
          return
        }
        if (pending) dismissFeed(pending.id)
        pending = postFeed(busy!)
      }
      const context = await getRunContext(chosen.project_id, controller.signal)
      const request = goal === MASS_GOAL && layout ? massRunRequest(site, conditions, layout)
        : goal === LAYOUT_GOAL && layout ? layoutRunRequest(site, conditions, layout) : siteRunRequest(site, conditions)
      const submitted = await submitRun(chosen.project_id, context, key, request, controller.signal, conversationId)
      if (!controller.signal.aborted) onRun(submitted)
    } catch (error) {
      if (controller.signal.aborted) return
      const failure = describeFailure(error)
      postFeed(requestFailedLine(failure))
      setState({ kind: 'failed', failure })
    } finally {
      // The busy line gives way to the receipt or the failure line.
      if (pending) dismissFeed(pending.id)
    }
  }, [chosen, conditions, state.kind, ready, site, setState, onRun])

  // The conversation's 법규·한계 검토 시작 answer lands here; what the card cannot do yet, it says so.
  useEffect(() => onCommand((command) => {
    if (command.kind !== 'start-review') return
    if (command.goal !== SITE_GOAL && !DESIGN_GOALS.includes(command.goal)) {
      // The card submits `limits`, `masterplan` and `mass`; another goal the catalog offers needs its own door first (fail closed).
      postFeed({ kind: 'error', agent: 'orchestrator', text: `'${command.goal}' 목표는 아직 대지 카드에서 보낼 수 없어요` })
      return
    }
    if (chosen && ready) {
      // A 배치 설계 asked from the conversation uses the card's remembered floor area and intent (the person's words).
      void start(command.goal as SiteGoal, DESIGN_GOALS.includes(command.goal) ? loadLayoutInputs() : undefined)
      return
    }
    postFeed({
      kind: 'error',
      agent: 'orchestrator',
      text: !chosen ? '검토를 보낼 프로젝트를 대지 카드에서 먼저 골라 주세요' : '기준일이 올바르지 않아요 — 대지 카드의 조건을 확인해 주세요',
      actions: [{ label: '대지 카드 열기', artifact: 'site-map' }, { label: '법규·한계 검토 시작', command }],
    })
  }), [chosen, ready, start])

  const phase: RunPhase = state.kind === 'submitted' ? { kind: 'submitted', run: state.run, stale } : state
  return { projects, chosen, setChosen, conditions, setConditions, ready, phase, start }
}
