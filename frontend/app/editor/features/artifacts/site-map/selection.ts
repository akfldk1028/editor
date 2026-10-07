import type { LngLat } from './engine/types'
import type { KnownParcel } from './parcelCache'

/** The facts the card shows for one parcel; the server fills them. */
export interface ParcelSummary {
  address: string
  land_category: string | null
  area_m2: number | null
  zones: string[]
}

export interface SiteParcel { pnu: string; address: string; lng: number; lat: number; summary: ParcelSummary }

/** A site = a bundle of parcels (they may be merged), in the order the user picked them. */
export interface SiteBundle {
  label: string
  parcels: SiteParcel[]
  total_area_m2: number | null
  /** Whether the parcels form one touching group (null: an outline was missing). */
  contiguous: boolean | null
  /** 용도지역 across all parcels. */
  zones: string[]
}

/** `preview` also returns outlines for drawing; they are never stored. */
export interface PreviewedSite extends SiteBundle {
  geometries: Record<string, object | null>
  outline: object | null
}

export interface SavedSite extends SiteBundle {
  selection_id: string
  created_at: string
  parcel_count: number
}

export interface Pick { pnu: string; at: LngLat }

const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(base() + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  })
  if (!response.ok) throw new Error(`요청 실패 (${response.status})`)
  return response.json() as Promise<T>
}

interface ReverseResponse { success: boolean; pnu: string | null; address: string | null; geometry: object | null; error?: string }

/** The point is on a road or outside any parcel. */
export class NoParcelError extends Error {
  constructor() { super('필지를 찾을 수 없어요') }
}

/** Point → parcel identity, address and outline (`reverse`, then `parcel-geometry` if it came without one). */
export async function parcelAt(at: LngLat, signal?: AbortSignal): Promise<KnownParcel> {
  const parcel = await post<ReverseResponse>('/api/v1/land/reverse', { x: at[0], y: at[1] }, signal)
  if (!parcel.success || !parcel.pnu) throw new NoParcelError()
  let geometry = parcel.geometry
  if (!geometry) {
    const outline = await post<{ success: boolean; geometry?: object; error?: string }>('/api/v1/land/parcel-geometry', { pnu: parcel.pnu }, signal)
    if (!outline.success || !outline.geometry) throw new Error(outline.error || '필지 경계를 찾지 못했습니다.')
    geometry = outline.geometry
  }
  return { pnu: parcel.pnu, address: parcel.address || '', geometry }
}

const picksBody = (picks: readonly Pick[]) => ({ parcels: picks.map(({ pnu, at }) => ({ pnu, lng: at[0], lat: at[1] })) })

/** The server describes the bundle (facts, adjacency, merged outline); nothing is stored. */
export function previewSite(picks: readonly Pick[], signal?: AbortSignal): Promise<PreviewedSite> {
  return post<PreviewedSite>('/api/v1/land/selections/preview', picksBody(picks), signal)
}

export function saveSite(picks: readonly Pick[]): Promise<SavedSite> {
  return post<SavedSite>('/api/v1/land/selections', picksBody(picks))
}

/** The last saved site, or null when none has been selected yet. */
export async function latestSite(signal?: AbortSignal): Promise<SavedSite | null> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/selections/latest`, { signal, cache: 'no-store' })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`선택한 대지를 불러오지 못했습니다 (${response.status})`)
  return response.json() as Promise<SavedSite>
}

/** Clicking a selected parcel deselects it; otherwise a click selects that parcel alone and adding (Shift or the card toggle) appends it. */
export function nextPicks(current: readonly Pick[], clicked: Pick, adding: boolean): Pick[] {
  if (current.some((pick) => pick.pnu === clicked.pnu)) return current.filter((pick) => pick.pnu !== clicked.pnu)
  return adding ? [...current, clicked] : [clicked]
}

export const savedPicks = (site: SiteBundle): Pick[] => site.parcels.map(({ pnu, lng, lat }) => ({ pnu, at: [lng, lat] as const }))
