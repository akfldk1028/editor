import { isPnu, pnuDigits } from '../../../land-map/lib/constants'

/** 고산 공공1 — the reference site until a project supplies its own. */
export const defaultSite = { query: '4115011300106840001', label: '고산 공공1 · 경기도 의정부시 산곡동 684-1' } as const

export interface Site {
  /** PNU or address, as `locateParcel` takes it. */
  query: string
  label: string
}

/** The site the shell's `pnu` (19 digits, hyphens allowed) or `address` parameter names, else null. */
export function siteParam(params: Readonly<Record<string, string>>): Site | null {
  const pnu = params.pnu?.trim()
  if (pnu && isPnu(pnu)) {
    const digits = pnuDigits(pnu)!
    return { query: digits, label: digits }
  }
  const address = params.address?.trim()
  if (address) return { query: address, label: address }
  return null
}

/** The site to open: the shell's `pnu` or `address` parameter, else the default. */
export function siteFromParams(params: Readonly<Record<string, string>>): Site {
  return siteParam(params) ?? { ...defaultSite }
}

/** A saved selection opens by its PNU, labelled with its address. */
export function siteFromSelection(selection: { pnu: string; address: string }): Site {
  return { query: selection.pnu, label: selection.address || selection.pnu }
}
