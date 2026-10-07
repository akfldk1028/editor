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
  if (!response.ok) {
    // The status and body stay in the console; the card shows a sentence.
    console.error(`[site-map] ${path} failed (${response.status})`, await response.text().catch(() => ''))
    throw new Error(response.status >= 500
      ? '서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.'
      : '요청을 처리하지 못했습니다. 다시 시도해 주세요.')
  }
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

/** Saves the bundle as the site of `scope` (a project id, or `default`). */
export function saveSite(picks: readonly Pick[], scope: string): Promise<SavedSite> {
  return post<SavedSite>('/api/v1/land/selections', { ...picksBody(picks), scope })
}

/** The scope a site is saved under: the shell's `?project=`, else `default`. */
export const selectionScope = (params: Readonly<Record<string, string>>): string =>
  /^[A-Za-z0-9_.-]{1,64}$/.test(params.project ?? '') ? params.project! : 'default'

/** The last site saved in `scope`, or null when none has been selected yet. */
export async function latestSite(scope: string, signal?: AbortSignal): Promise<SavedSite | null> {
  const query = new URLSearchParams({ scope })
  const response = await fetch(`${base()}/api/v1/land/selections/latest?${query}`, { signal, cache: 'no-store' })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`선택한 대지를 불러오지 못했습니다 (${response.status})`)
  return response.json() as Promise<SavedSite>
}

/**
 * Adding (Shift or the card toggle) adds or removes the clicked parcel. A plain click selects that
 * parcel alone — also one inside a bundle — and clicking the only selected parcel deselects it.
 */
export function nextPicks(current: readonly Pick[], clicked: Pick, adding: boolean): Pick[] {
  const selected = current.some((pick) => pick.pnu === clicked.pnu)
  if (adding) return selected ? current.filter((pick) => pick.pnu !== clicked.pnu) : [...current, clicked]
  return selected && current.length === 1 ? [] : [clicked]
}

export const savedPicks = (site: SiteBundle): Pick[] => site.parcels.map(({ pnu, lng, lat }) => ({ pnu, at: [lng, lat] as const }))
