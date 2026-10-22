'use client'

import { useCallback, useEffect, useState } from 'react'
import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import {
  getAlternatives,
  latestRun,
  resumeRun,
  selectAlternative,
} from '@/lib/orchestrator-runs/api'
import { isTerminal } from '@/lib/orchestrator-runs/labels'
import type {
  LayoutAlternatives,
  LayoutCandidate,
  MassCandidate,
  RunMasterplan,
  RunWithResults,
} from '@/lib/orchestrator-runs/types'
import type { LayoutOverlay } from '../ui/World3D'
import { SITE_RUN_EVENT } from './useSiteRun'

const RECHECK_MS = 20_000

/** The caption the 3D corner shows for a layout: storeys and the basis the result names, or why nothing is drawn. */
export function layoutCaption(plan: RunMasterplan, runId: string): string {
  const layout = plan.layout
  if (!layout)
    return plan.truncated
      ? '배치 결과가 잘려 그리지 못했어요'
      : `배치 ${plan.status}: 그릴 도형이 없어요`
  const storeys = layout.storeys
    ? `${layout.storeys}층 (${layout.height_basis ?? '층고 가정'})`
    : (layout.height_basis ?? '층수 미정')
  const footprint =
    layout.footprint_m2 != null ? ` · 바닥 ${Math.round(layout.footprint_m2)}㎡` : ''
  return `배치 ${runId.slice(0, 8)} · ${storeys}${footprint}`
}

/** What the 3D view draws from a masterplan result: null when it holds no layout. */
export function overlayOf(
  plan: RunMasterplan | null | undefined,
  runId: string,
): LayoutOverlay | null {
  if (!plan?.layout) return null
  return {
    layout: plan.layout,
    intent: plan.intent as LayoutOverlay['intent'],
    caption: layoutCaption(plan, runId),
    runId,
  }
}

/** A candidate of the selection set standing on the parcel, named by its label (the pick, or the one being looked at). */
export function candidateOverlay(
  candidate: LayoutCandidate | null | undefined,
  runId: string,
  confirmed: boolean,
): LayoutOverlay | null {
  const overlay = overlayOf(candidate?.masterplan, runId)
  if (!overlay || !candidate) return null
  const storeys = overlay.layout.storeys ? ` · ${overlay.layout.storeys}층` : ''
  const footprint =
    overlay.layout.footprint_m2 != null
      ? ` · 바닥 ${Math.round(overlay.layout.footprint_m2)}㎡`
      : ''
  return {
    ...overlay,
    caption: `${confirmed ? '고른 배치안' : '배치안 보기'}: ${candidate.label ?? candidate.candidate_id}${storeys}${footprint}`,
  }
}

/** The forms Mass offers when a 매스 설계 run waits for the person's pick (`mass_selection`); empty otherwise. */
export function massQuestionOf(run: RunWithResults | null | undefined): MassCandidate[] {
  const question = run?.pending_request
  if (
    !run ||
    run.status !== 'waiting_input' ||
    !question ||
    question.kind !== 'mass_selection' ||
    !Array.isArray(question.candidates)
  )
    return []
  return (question.candidates as unknown[]).filter(
    (c): c is MassCandidate => typeof (c as MassCandidate)?.selected_mass_id === 'string',
  )
}

/** The candidate the 3D view stands on the parcel: the one being looked at, else the pick, else the first. */
export function shownCandidate(
  alternatives: LayoutAlternatives | null,
  preview: string | null,
): LayoutCandidate | null {
  if (!alternatives?.candidates.length) return null
  const byId = (id: string | null) =>
    id ? (alternatives.candidates.find((c) => c.candidate_id === id) ?? null) : null
  return (
    byId(preview) ?? byId(alternatives.chosen_candidate_id) ?? alternatives.candidates[0] ?? null
  )
}

export interface LayoutChoice {
  /** What the 3D view draws now: the candidate being looked at or picked, else the run's own layout. */
  overlay: LayoutOverlay | null
  /** The newest 배치 설계 of the parcel (a continuation of a pick counts as one). */
  run: RunWithResults | null
  /** MasterPlan's candidates and the pick so far; null while the run has none. */
  alternatives: LayoutAlternatives | null
  preview: string | null
  setPreview(candidateId: string | null): void
  /** Confirms a candidate: the Orchestrator records the pick and continues it as the project's newest 배치 설계. */
  choose(candidateId: string): Promise<void>
  choosing: boolean
  /** The newest 매스 설계 of the parcel and, while it waits, the forms Mass offers. */
  massRun: RunWithResults | null
  massCandidates: MassCandidate[]
  chooseMass(selectedMassId: string): Promise<void>
  massBusy: boolean
  error: string | null
}

/**
 * The newest 배치 설계 of this parcel under the chosen project, its selection set and the newest 매스 설계: fetched
 * when the parcel or project changes, again when a site run is submitted, picked or finishes (SITE_RUN_EVENT), and
 * every RECHECK_MS while a run is still open or waiting for a pick.
 */
export function useLatestLayout(
  projectParam: string | undefined,
  pnu: string | null,
  active: boolean,
): LayoutChoice {
  const { chosen } = useProjectBinding(projectParam)
  const [run, setRun] = useState<RunWithResults | null>(null)
  const [alternatives, setAlternatives] = useState<LayoutAlternatives | null>(null)
  const [massRun, setMassRun] = useState<RunWithResults | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [choosing, setChoosing] = useState(false)
  const [massBusy, setMassBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const bump = () => setTick((n) => n + 1)
    window.addEventListener(SITE_RUN_EVENT, bump)
    return () => window.removeEventListener(SITE_RUN_EVENT, bump)
  }, [])
  useEffect(() => {
    if (!open || !active) return
    const timer = setInterval(() => setTick((n) => n + 1), RECHECK_MS)
    return () => clearInterval(timer)
  }, [open, active])
  useEffect(() => {
    if (!chosen || !pnu || !active) return
    const controller = new AbortController()
    const projectId = chosen.project_id
    void (async () => {
      try {
        const [found, mass] = await Promise.all([
          latestRun(projectId, 'masterplan', pnu, controller.signal),
          latestRun(projectId, 'mass', pnu, controller.signal),
        ])
        if (controller.signal.aborted) return
        const set = found ? await getAlternatives(projectId, found.run_id, controller.signal) : null
        if (controller.signal.aborted) return
        setRun(found)
        setAlternatives(set)
        setMassRun(mass)
        setPreview((current) =>
          current && set?.candidates.some((c) => c.candidate_id === current) ? current : null,
        )
        setOpen(
          (found ? !isTerminal(found.status) : false) ||
            (mass ? !isTerminal(mass.status) && mass.status !== 'waiting_input' : false),
        )
      } catch {
        if (!controller.signal.aborted) setOpen(false)
      }
    })()
    return () => controller.abort()
  }, [chosen, pnu, active, tick])

  const choose = useCallback(
    async (candidateId: string) => {
      if (!chosen || !run || choosing) return
      setChoosing(true)
      setError(null)
      try {
        // A continuation shows its parent's set: the pick goes to the run that owns the set.
        const owner = alternatives?.run_id ?? run.run_id
        await selectAlternative(chosen.project_id, owner, candidateId)
        setPreview(candidateId)
        window.dispatchEvent(
          new CustomEvent(SITE_RUN_EVENT, {
            detail: { run_id: owner, goal: 'masterplan', status: 'selected' },
          }),
        )
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : '배치안을 고르지 못했어요')
      } finally {
        setChoosing(false)
      }
    },
    [chosen, run, alternatives, choosing],
  )

  const chooseMass = useCallback(
    async (selectedMassId: string) => {
      if (!chosen || !massRun || massBusy) return
      setMassBusy(true)
      setError(null)
      try {
        await resumeRun(chosen.project_id, massRun.run_id, { selected_mass_id: selectedMassId })
        window.dispatchEvent(
          new CustomEvent(SITE_RUN_EVENT, {
            detail: { run_id: massRun.run_id, goal: 'mass', status: 'resumed' },
          }),
        )
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : '매스 안을 고르지 못했어요')
      } finally {
        setMassBusy(false)
      }
    },
    [chosen, massRun, massBusy],
  )

  const shown = shownCandidate(alternatives, preview)
  const overlay = run
    ? shown
      ? candidateOverlay(
          shown,
          run.run_id,
          shown.candidate_id === alternatives?.chosen_candidate_id,
        )
      : overlayOf(run.results.masterplan, run.run_id)
    : null
  return {
    overlay,
    run,
    alternatives,
    preview,
    setPreview,
    choose,
    choosing,
    massRun,
    massCandidates: massQuestionOf(massRun),
    chooseMass,
    massBusy,
    error,
  }
}
