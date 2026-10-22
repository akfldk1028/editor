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

/**
 * What a 배치 설계 asks beyond the 조건: the floor area wanted, the ground footprint wanted (the building-zone target the
 * placement engine searches with; the legal coverage ceiling is never used as one) and the intent in the person's own words.
 */
export interface LayoutInputs {
  floorAreaM2: string
  footprintM2: string
  intent: string
  /** The parking planned (대수) and at most this many on the ground; both optional. Without them the engine plans the
   * legal minimum, which usually fits on the ground — no basement, no ramp. */
  parkingStalls: string
  maxSurfaceStalls: string
}

export const LAYOUT_STORAGE_KEY = 'site-layout-inputs'
export const defaultLayoutInputs = (): LayoutInputs => ({ floorAreaM2: '', footprintM2: '', intent: '', parkingStalls: '', maxSurfaceStalls: '' })

/** A stall count typed (0 ~ 10,000, whole); '' is "not given" (undefined); anything else is null (blocked). */
const stalls = (text: string): number | null | undefined => {
  const trimmed = text.replace(/,/g, '').trim()
  if (!trimmed) return undefined
  const value = Number(trimmed)
  return Number.isInteger(value) && value >= 0 && value <= 10_000 ? value : null
}

const area = (text: string): number | null => {
  const value = Number(text.replace(/,/g, '').trim())
  return Number.isFinite(value) && value >= 1 && value <= 10_000_000 ? value : null
}

/** The floor area as a number the door accepts (1 ~ 10,000,000 ㎡), else null. */
export const floorArea = (inputs: LayoutInputs): number | null => area(inputs.floorAreaM2)

/** The ground footprint wanted as a number the door accepts (1 ㎡ up to the floor area), else null. */
export function footprintArea(inputs: LayoutInputs): number | null {
  const value = area(inputs.footprintM2)
  const total = floorArea(inputs)
  return value !== null && total !== null && value <= total ? value : null
}

/** Why a 배치 설계 cannot be sent yet, in Korean; null when it can. */
export function layoutBlocker(conditions: RunConditions, inputs: LayoutInputs): string | null {
  if (!conditions.buildingType.trim()) return '용도를 골라 주세요 — 배치는 용도가 있어야 그려요'
  if (floorArea(inputs) === null) return '연면적(㎡)을 숫자로 적어 주세요'
  if (area(inputs.footprintM2) === null) return '건물 바닥면적(㎡)을 숫자로 적어 주세요 — 건물이 땅에 닿는 면적이에요'
  if (footprintArea(inputs) === null) return '바닥면적은 연면적보다 클 수 없어요'
  if (inputs.intent.trim().length > 2000) return '설계 의도는 2,000자 안으로 적어 주세요'
  const total = stalls(inputs.parkingStalls)
  const ground = stalls(inputs.maxSurfaceStalls)
  if (total === null || ground === null) return '주차 대수는 0 이상의 정수로 적어 주세요'
  if (ground !== undefined && total === undefined) return '지상 최대 대수를 쓰려면 주차 대수도 적어 주세요'
  if (ground !== undefined && total !== undefined && ground > total) return '지상 최대 대수는 주차 대수보다 클 수 없어요'
  return null
}

/**
 * The Orchestrator's `masterplan` request (배치 설계): the same parcel bundle and 조건 as `limits`, the floor area and
 * ground footprint wanted, and the intent exactly as typed — the door turns the sentence into the intent owner's declaration.
 */
export function layoutRunRequest(site: SavedSite, conditions: RunConditions, inputs: LayoutInputs): RunRequest {
  const parcels = site.parcels.map((parcel) => parcel.pnu)
  const intent = inputs.intent.trim()
  return {
    goal: 'masterplan', pnu: parcels[0]!, parcels, assessment_date: conditions.assessmentDate,
    building_type: conditions.buildingType.trim(), floor_area_m2: floorArea(inputs) ?? 0, footprint_m2: footprintArea(inputs) ?? 0,
    ...(intent ? { intent } : {}),
    ...(typeof stalls(inputs.parkingStalls) === 'number' ? { parking_stalls: stalls(inputs.parkingStalls)! } : {}),
    ...(typeof stalls(inputs.maxSurfaceStalls) === 'number' ? { max_surface_stalls: stalls(inputs.maxSurfaceStalls)! } : {}),
  }
}

/** 매스 설계 (`mass`): the same inputs; the Orchestrator builds on the layout the person chose and asks which form to keep. */
export function massRunRequest(site: SavedSite, conditions: RunConditions, inputs: LayoutInputs): RunRequest {
  const layout = layoutRunRequest(site, conditions, inputs) as Extract<RunRequest, { goal: 'masterplan' }>
  // The footprint target steers the layout search only; a 매스 설계 stands on the layout already chosen, and the
  // Orchestrator's `mass` goal refuses inputs it does not read (run submit 409, 2026-10-22).
  const { footprint_m2: _footprint, parking_stalls: _parking, max_surface_stalls: _surface, ...rest } = layout
  return { ...rest, goal: 'mass' }
}

type Store = Pick<Storage, 'getItem' | 'setItem'>

export function loadLayoutInputs(storage?: Store): LayoutInputs {
  try {
    const raw = (storage ?? globalThis.localStorage)?.getItem(LAYOUT_STORAGE_KEY)
    const saved = raw ? (JSON.parse(raw) as Partial<LayoutInputs> | null) : null
    return {
      floorAreaM2: typeof saved?.floorAreaM2 === 'string' ? saved.floorAreaM2.slice(0, 20) : '',
      footprintM2: typeof saved?.footprintM2 === 'string' ? saved.footprintM2.slice(0, 20) : '',
      intent: typeof saved?.intent === 'string' ? saved.intent.slice(0, 2000) : '',
      parkingStalls: typeof saved?.parkingStalls === 'string' ? saved.parkingStalls.slice(0, 8) : '',
      maxSurfaceStalls: typeof saved?.maxSurfaceStalls === 'string' ? saved.maxSurfaceStalls.slice(0, 8) : '',
    }
  } catch {
    return defaultLayoutInputs()
  }
}

export function saveLayoutInputs(inputs: LayoutInputs, storage?: Store): void {
  try {
    (storage ?? globalThis.localStorage)?.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(inputs))
  } catch {
    // nothing remembered: the next 배치 설계 starts from empty fields
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
