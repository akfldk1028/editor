import { isTerminal } from '@/lib/orchestrator-runs/labels'
import { idempotencyKey as keyFor, NOT_CONTIGUOUS, NOT_CONTIGUOUS_TEXT } from '@/lib/orchestrator-runs/submit'
import type { RunRequest, RunSummary } from '@/lib/orchestrator-runs/types'

import type { SavedSite } from './picks'
import type { RunConditions } from './run-conditions'

/** Shared with the law artifact: project choice, Korean statuses and refusals live in `lib/orchestrator-runs`. */
export { isTerminal, statusLabel, traceLabel } from '@/lib/orchestrator-runs/labels'
export { describeFailure, type ProjectChoice, resolveProject, type RunFailure } from '@/lib/orchestrator-runs/submit'

/**
 * The Orchestrator's `limits` request: `pnu` leads `parcels` (the whole bundle, in pick order; Site
 * merges a touching bundle and refuses one that is not), the 기준일, and the 용도 when one is chosen.
 */
export function siteRunRequest(site: SavedSite, conditions: RunConditions): RunRequest {
  const parcels = site.parcels.map((parcel) => parcel.pnu)
  const buildingType = conditions.buildingType.trim()
  return {
    goal: 'limits', pnu: parcels[0]!, parcels, assessment_date: conditions.assessmentDate,
    ...(buildingType ? { building_type: buildingType } : {}),
  }
}

/** Shown before the button: a bundle the map found not touching will be refused by Site. */
export function bundleNotice(site: SavedSite): string | null {
  return site.contiguous === false ? `서로 붙어 있지 않은 묶음은 합필 검토가 거절돼요 (${NOT_CONTIGUOUS})` : null
}

/** One key per attempt (the header allows `[A-Za-z0-9_-]{1,128}`); the same key replays the same run. */
export function idempotencyKey(site: SavedSite, attempt: number): string {
  return keyFor('site', site.selection_id, attempt)
}

/** Under a terminal run: what the agents refused, in Korean, when the status alone does not say. */
export function runNotice(run: Pick<RunSummary, 'status' | 'communications'>): string | null {
  if (!isTerminal(run.status)) return null
  if (run.communications.some((item) => item.state === 'failed' && (item.response_text ?? '').includes(NOT_CONTIGUOUS))) return NOT_CONTIGUOUS_TEXT
  return null
}
