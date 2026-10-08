/**
 * The goal catalog as the conversation uses it: fetched once per session from
 * `GET /platform/capabilities`, with a fallback that names only what the door has always taken, so
 * the choices after a site is selected are DERIVED — no button is spelled in a component. A goal the
 * Orchestrator opens later becomes a choice by appearing here.
 */
import { getCapabilities } from '@/lib/orchestrator-runs/api'
import type { Capabilities, Goal } from '@/lib/orchestrator-runs/types'

/** What the editor door has taken since 2026-10-08; used when the catalog cannot be fetched. */
export const FALLBACK: Capabilities = {
  goals: [{ id: 'limits', label: '법규·한계 검토', owners: ['site_context', 'law', 'revision'], inputs: ['pnu', 'assessment_date'], optional: ['building_type', 'parcels'], available: true, offer: true }],
  conversation: { ask: true, law_analysis: true },
  source: 'fallback',
}

let loaded: Promise<Capabilities> | null = null

/** The catalog, fetched once; a failed fetch yields the fallback and is retried on the next call. */
export function loadCapabilities(signal?: AbortSignal): Promise<Capabilities> {
  if (!loaded) {
    loaded = getCapabilities(signal).catch(() => {
      loaded = null
      return FALLBACK
    })
  }
  return loaded
}

/** The goals the conversation offers after a site is selected: available at the door and marked to offer. */
export const offeredGoals = (capabilities: Capabilities): Goal[] => capabilities.goals.filter((goal) => goal.available && goal.offer)

/** The goal by id, when the door takes it. */
export const availableGoal = (capabilities: Capabilities, id: string): Goal | null => capabilities.goals.find((goal) => goal.id === id && goal.available) ?? null

/** Test seam. */
export function resetCapabilities(): void {
  loaded = null
}
