import { isPnu } from '../../land-map/lib/constants'

/** 고산 공공1 — the reference site until a project supplies its own. */
export const defaultSite = { query: '4115011300106840001', label: '고산 공공1 · 경기도 의정부시 산곡동 684-1' } as const

export interface Site {
  /** PNU or address, as `locateParcel` takes it. */
  query: string
  label: string
}

/** The site to open: the shell's `pnu` (19 digits) or `address` parameter, else the default. */
export function siteFromParams(params: Readonly<Record<string, string>>): Site {
  const pnu = params.pnu?.trim()
  if (pnu && isPnu(pnu)) return { query: pnu, label: pnu }
  const address = params.address?.trim()
  if (address) return { query: address, label: address }
  return { ...defaultSite }
}
