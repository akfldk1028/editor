'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import { useScopedState } from '@/lib/design-conversation/useScopedState'
import { rememberConversationLawRun, rememberConversationSite } from '@/lib/design-conversation/context'

import { getResults, getRunContext, latestRun, submitRun } from '@/lib/orchestrator-runs/api'
import { defaultRunConditions, isValidDate, loadRunConditions, type RunConditions, saveRunConditions } from '@/lib/orchestrator-runs/conditions'
import { dismissFeed, projectFeed } from '@/lib/orchestrator-runs/feed'
import { requestFailedLine, requestingLines } from '@/lib/orchestrator-runs/feed-lines'
import { isTerminal } from '@/lib/orchestrator-runs/labels'
import { useRunPolling } from '@/lib/orchestrator-runs/poll'
import { describeFailure, idempotencyKey, type ProjectChoice, type RunFailure } from '@/lib/orchestrator-runs/submit'
import type { RunResults, RunSummary } from '@/lib/orchestrator-runs/types'
import { useRunFeed } from '@/lib/orchestrator-runs/useRunFeed'

export type Projects = { kind: 'loading' } | { kind: 'error'; text: string } | ProjectChoice

export type ReviewPhase =
  | { kind: 'loading' }
  | { kind: 'error'; text: string }
  /** The project has no `limits` run for this parcel yet. */
  | { kind: 'empty' }
  | { kind: 'run'; run: RunSummary; results: RunResults | null; stale: boolean }

const LAW_TOOL = 'law_parcel_limits'

/**
 * The Orchestrator's review of one parcel: the project binding (same rule as the site card), the
 * newest `limits` run for the parcel (`GET /projects/{id}/runs/latest`), its parsed results, and a
 * 검토 시작 that submits a new run and follows it (shared poller). Runs started here reach the
 * conversation feed; a run merely found by `latest` does not (it already happened).
 */
export function useOrchestratorReview(pnu: string | null, address: string, projectParam: string | undefined) {
  const { projects, chosen, setChosen, conversationId } = useProjectBinding(projectParam)
  const scope = JSON.stringify([chosen?.project_id, conversationId, pnu])
  const [conditions, setConditions] = useState<RunConditions>(defaultRunConditions)
  const [run, setRun] = useScopedState<RunSummary | null>(scope, null)
  const [results, setResults] = useScopedState<RunResults | null>(scope, null)
  const [load, setLoad] = useScopedState<{ kind: 'loading' } | { kind: 'error'; text: string } | { kind: 'ready' }>(scope, { kind: 'loading' })
  const [submitting, setSubmitting] = useScopedState(scope, false)
  const [failure, setFailure] = useScopedState<RunFailure | null>(scope, null)
  const [reloads, setReloads] = useState(0)
  // Per-mount nonce (see useSiteRun): a reload must not replay a key whose run already changed the sources.
  const attempts = useRef(Math.floor(Date.now() / 1000) % 1_000_000)
  const active = useRef<AbortController | null>(null)
  /** Which run snapshot the results belong to, so a poll refreshes them once per change. */
  const resultsFor = useRef<string | null>(null)
  const startedHere = useRef(new Set<string>())
  const siteOwner = useRef<{ pnu: string; projectId: string } | null>(null)
  const ready = isValidDate(conditions.assessmentDate)

  useEffect(() => setConditions(loadRunConditions()), [])
  useEffect(() => {
    if (!chosen || !pnu) return
    if (!siteOwner.current || siteOwner.current.pnu !== pnu) siteOwner.current = { pnu, projectId: chosen.project_id }
    if (siteOwner.current.projectId === chosen.project_id) rememberConversationSite(chosen.project_id, { pnu, address }, conditions.assessmentDate)
  }, [chosen, pnu, address, conditions.assessmentDate])

  const snapshot = (value: RunSummary) => `${value.run_id}:${value.status}:${value.communications.length}`

  // The newest run for this parcel, once the project is known (and again on 다시 확인).
  useEffect(() => {
    if (!chosen || !pnu) return
    const controller = new AbortController()
    setLoad({ kind: 'loading' })
    latestRun(chosen.project_id, 'limits', pnu, controller.signal)
      .then((found) => {
        if (controller.signal.aborted) return
        if (found) {
          const { results: parsed, ...summary } = found
          if (parsed.request?.pnu === pnu) {
            rememberConversationLawRun(chosen.project_id, pnu, summary.run_id, parsed)
          }
          resultsFor.current = snapshot(summary)
          setRun(summary)
          setResults(parsed)
        } else {
          setRun(null)
          setResults(null)
        }
        setLoad({ kind: 'ready' })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoad({ kind: 'error', text: error instanceof Error ? error.message : '검토 실행을 불러오지 못했어요.' })
      })
    return () => controller.abort()
  }, [chosen, pnu, address, reloads, conversationId])

  const onRun = useCallback((next: RunSummary) => setRun(next), [setRun])
  const { stale } = useRunPolling(chosen?.project_id ?? null, run, onRun)
  useRunFeed(run && startedHere.current.has(`${conversationId}:${run.run_id}`) ? run : null, { projectId: chosen?.project_id ?? null, conversationId, pnu: pnu ?? '', address, project: chosen?.project_id })

  // Results follow the run: refreshed when Law's step has answered or the run ended, once per snapshot.
  useEffect(() => {
    if (!run || !chosen) return
    const key = snapshot(run)
    if (resultsFor.current === key) return
    const lawDone = run.communications.some((comm) => comm.tool === LAW_TOOL && comm.state === 'succeeded')
    if (!lawDone && !isTerminal(run.status)) return
    resultsFor.current = key
    const controller = new AbortController()
    getResults(chosen.project_id, run.run_id, controller.signal)
      .then((parsed) => {
        if (!controller.signal.aborted) {
          rememberConversationLawRun(chosen.project_id, pnu ?? '', run.run_id, parsed)
          setResults(parsed)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted && resultsFor.current === key) resultsFor.current = null
      })
    return () => controller.abort()
  }, [run, chosen])

  useEffect(() => () => active.current?.abort(), [scope])

  const start = useCallback(async () => {
    if (!chosen || !pnu || !ready || submitting) return
    const postFeed = projectFeed(chosen.project_id)
    siteOwner.current = { pnu, projectId: chosen.project_id }
    rememberConversationSite(chosen.project_id, { pnu, address }, conditions.assessmentDate)
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setSubmitting(true)
    setFailure(null)
    saveRunConditions(conditions)
    const [bubble, busy] = requestingLines(address || pnu, conditions)
    postFeed(bubble!)
    const pending = postFeed(busy!)
    const buildingType = conditions.buildingType.trim()
    try {
      const context = await getRunContext(chosen.project_id, controller.signal)
      const submitted = await submitRun(chosen.project_id, context, idempotencyKey('law', pnu, ++attempts.current), {
        goal: 'limits', pnu, parcels: [pnu], assessment_date: conditions.assessmentDate, ...(buildingType ? { building_type: buildingType } : {}),
      }, controller.signal, conversationId)
      if (controller.signal.aborted) return
      startedHere.current.add(`${conversationId}:${submitted.run_id}`)
      resultsFor.current = null
      setRun(submitted)
      setResults(null)
      setLoad({ kind: 'ready' })
    } catch (error) {
      if (controller.signal.aborted) return
      const failure = describeFailure(error)
      postFeed(requestFailedLine(failure))
      setFailure(failure)
    } finally {
      // The busy line gives way to the receipt or the failure line.
      if (pending) dismissFeed(pending.id)
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [chosen, pnu, ready, submitting, conditions, address, conversationId])

  const reload = useCallback(() => setReloads((count) => count + 1), [])

  const phase: ReviewPhase = load.kind === 'loading' ? { kind: 'loading' } : load.kind === 'error' ? load : run ? { kind: 'run', run, results, stale } : { kind: 'empty' }
  return { projects, chosen, setChosen, conditions, setConditions, ready, phase, submitting, failure, start, reload }
}
