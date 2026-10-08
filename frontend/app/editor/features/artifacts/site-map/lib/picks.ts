import type { LngLat } from './engine/types'

/** A parcel from `reverse`: identity, address and outline. */
export interface KnownParcel { pnu: string; address: string; geometry: object }

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

export interface SavedSite extends SiteBundle {
  selection_id: string
  created_at: string
  parcel_count: number
}

export interface Pick { pnu: string; at: LngLat }

/** The scope a site is saved under: the shell's `?project=`, else `default`. */
export const selectionScope = (params: Readonly<Record<string, string>>): string =>
  /^[A-Za-z0-9_.-]{1,64}$/.test(params.project ?? '') ? params.project! : 'default'

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
