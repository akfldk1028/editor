import type { LngLat } from '../lib/engine/types'
import type { KnownParcel, Pick, SavedSite, SiteBundle } from '../lib/picks'

/** `preview` also returns outlines for drawing; they are never stored. */
export interface PreviewedSite extends SiteBundle {
  geometries: Record<string, object | null>
  outline: object | null
}

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

/** A saved site's outlines and merged boundary for redrawing; its facts are already in the record. */
export function siteOutlines(pnus: readonly string[], signal?: AbortSignal): Promise<{ geometries: PreviewedSite['geometries']; outline: PreviewedSite['outline'] }> {
  return post('/api/v1/land/selections/outlines', { pnus }, signal)
}

/** Saves the bundle as the site of `scope` (a project id, or `default`). */
export function saveSite(picks: readonly Pick[], scope: string): Promise<SavedSite> {
  return post<SavedSite>('/api/v1/land/selections', { ...picksBody(picks), scope })
}

/** The last site saved in `scope`, or null when none has been selected yet. */
export async function latestSite(scope: string, signal?: AbortSignal): Promise<SavedSite | null> {
  const query = new URLSearchParams({ scope })
  const response = await fetch(`${base()}/api/v1/land/selections/latest?${query}`, { signal, cache: 'no-store' })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`선택한 대지를 불러오지 못했습니다 (${response.status})`)
  return response.json() as Promise<SavedSite>
}
