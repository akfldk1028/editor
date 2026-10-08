/** The last saved site of a scope (`GET /land/selections/latest`); only the fields this slice reads. */

export interface SavedSiteParcel { pnu: string; address: string }

export interface SavedSite {
  selection_id: string
  label: string
  parcels: SavedSiteParcel[]
  total_area_m2: number | null
}

/** The scope a site is saved under: the shell's `?project=`, else `default` (same rule as the site map). */
export const selectionScope = (params: Readonly<Record<string, string>>): string =>
  /^[A-Za-z0-9_.-]{1,64}$/.test(params.project ?? '') ? params.project! : 'default'

export async function latestSite(scope: string, signal?: AbortSignal): Promise<SavedSite | null> {
  const query = new URLSearchParams({ scope })
  const base = process.env.NEXT_PUBLIC_BASE_PATH || ''
  const response = await fetch(`${base}/api/v1/land/selections/latest?${query}`, { signal, cache: 'no-store' })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`선택한 대지를 불러오지 못했습니다 (${response.status})`)
  return response.json() as Promise<SavedSite>
}
