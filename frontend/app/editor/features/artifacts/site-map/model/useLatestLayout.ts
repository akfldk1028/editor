'use client'

import { useEffect, useState } from 'react'

import { latestRun } from '@/lib/orchestrator-runs/api'
import { isTerminal } from '@/lib/orchestrator-runs/labels'
import type { MassForms, RunMasterplan } from '@/lib/orchestrator-runs/types'
import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import type { LayoutOverlay } from '../ui/World3D'
import { SITE_RUN_EVENT } from './useSiteRun'

const RECHECK_MS = 20_000

/** The caption the 3D corner shows for a layout: storeys and the basis the result names, or why nothing is drawn. */
export function layoutCaption(plan: RunMasterplan, runId: string): string {
  const layout = plan.layout
  if (!layout) return plan.truncated ? '배치 결과가 잘려 그리지 못했어요' : `배치 ${plan.status}: 그릴 도형이 없어요`
  const storeys = layout.storeys ? `${layout.storeys}층 (${layout.height_basis ?? '층고 가정'})` : (layout.height_basis ?? '층수 미정')
  const footprint = layout.footprint_m2 != null ? ` · 바닥 ${Math.round(layout.footprint_m2)}㎡` : ''
  return `배치 ${runId.slice(0, 8)} · ${storeys}${footprint}`
}

/** What the 3D view draws from a masterplan result: null when it holds no layout. */
export function overlayOf(plan: RunMasterplan | null | undefined, runId: string, forms: MassForms | null = null): LayoutOverlay | null {
  if (!plan?.layout) return null
  return { layout: plan.layout, intent: plan.intent as LayoutOverlay['intent'], caption: layoutCaption(plan, runId), forms, runId }
}

/** The form a run opens with: the first that reaches the floor-area target, else the first. */
export function defaultForm(forms: MassForms | null | undefined): string | null {
  const list = forms?.alternatives ?? []
  return (list.find((f) => f.reaches_target) ?? list[0])?.id ?? null
}

/** The overlay with the chosen Mass form standing on the zone, and the caption naming it. */
export function withForm(overlay: LayoutOverlay | null, formId: string | null): LayoutOverlay | null {
  const form = overlay?.forms?.alternatives.find((f) => f.id === formId)
  if (!overlay || !form?.volumes.length) return overlay
  const storeys = form.storeys ? `${form.storeys}층` : ''
  const area = form.gfa_m2 != null ? ` · 연면적 ${Math.round(form.gfa_m2).toLocaleString()}㎡` : ''
  return {
    ...overlay,
    layout: { ...overlay.layout, mass: { label: form.label, volumes: form.volumes } },
    caption: `배치 ${overlay.runId?.slice(0, 8) ?? ''} · ${form.label ?? 'Mass 안'} ${storeys}${area}`,
  }
}

/**
 * The newest 배치 설계 of this parcel under the chosen project: fetched when the parcel or project changes, again
 * when a site run is submitted or finishes (SITE_RUN_EVENT), and every RECHECK_MS while that run is still open.
 */
export function useLatestLayout(projectParam: string | undefined, pnu: string | null, active: boolean): LayoutOverlay | null {
  const { chosen } = useProjectBinding(projectParam)
  const [overlay, setOverlay] = useState<LayoutOverlay | null>(null)
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
    latestRun(chosen.project_id, 'masterplan', pnu, controller.signal)
      .then((found) => {
        if (controller.signal.aborted) return
        setOpen(found ? !isTerminal(found.status) : false)
        setOverlay(found ? overlayOf(found.results.masterplan, found.run_id, found.results.mass_forms ?? null) : null)
      })
      .catch(() => { if (!controller.signal.aborted) setOpen(false) })
    return () => controller.abort()
  }, [chosen, pnu, active, tick])
  return overlay
}
