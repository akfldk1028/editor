/** The site map's search box, without React: when to search, what each row says, what Enter does. Pure. */
import type { SearchCandidate, SearchResult } from '../../../land-map/lib/land-api-client'

/** Typing waits this long before it asks; Enter asks at once. */
export const SEARCH_DEBOUNCE_MS = 250
export const SEARCH_MIN_CHARS = 2

export const BADGES: Record<SearchCandidate['kind'], string> = { lot: '지번', road: '도로명', place: '장소', area: '지역' }

/** Two characters or more (a PNU, 산곡동, 강남역); a single syllable lists half the country. */
export function shouldSearch(text: string): boolean {
  return text.trim().length >= SEARCH_MIN_CHARS
}

/** The second line of a row: the road address of a lot, the lot of a road address or a place; nothing for an area. */
export function candidateDetail(candidate: SearchCandidate): string | null {
  if (candidate.kind === 'lot') return candidate.road
  if (candidate.kind === 'road' || candidate.kind === 'place') return candidate.jibun
  return null
}

/** A key per row: the parcel, else the label at its point. */
export function candidateKey(candidate: SearchCandidate): string {
  return `${candidate.kind}:${candidate.pnu ?? ''}:${candidate.label}:${candidate.point.join(',')}`
}

/** One sentence above the rows, or null when the rows speak for themselves. */
export function searchNotice(result: SearchResult): string | null {
  if (result.status === 'none' || result.status === 'unavailable') return result.error ?? '찾지 못했어요.'
  const [top] = result.candidates
  if (!top) return null
  if (top.substituted) {
    const what = top.kind === 'road' ? '주소는' : '지번은'
    return `입력한 ${what} 없고 가장 가까운 ${top.label} 입니다`
  }
  const exact = result.candidates.filter((candidate) => candidate.exact && (candidate.kind === 'lot' || candidate.kind === 'road'))
  if (exact.length > 1) return `같은 번지가 ${exact.length}곳에 있어요 — 골라 주세요`
  return null
}

/** What Enter does with an answer: open the one parcel, zoom to the one area, or leave the list open to choose. */
export type EnterAction = { kind: 'select'; candidate: SearchCandidate } | { kind: 'zoom'; candidate: SearchCandidate } | { kind: 'list' }

export function enterAction(result: SearchResult): EnterAction {
  const [top] = result.candidates
  if (result.status === 'unique' && top) return top.pnu ? { kind: 'select', candidate: top } : { kind: 'zoom', candidate: top }
  if (result.candidates.length === 1 && top?.kind === 'area') return { kind: 'zoom', candidate: top }
  return { kind: 'list' }
}

/** The rows answer the text in the box now (not an older text still on screen while the next search waits). */
export function rowsAreCurrent(answeredFor: string, typed: string): boolean {
  return answeredFor.trim() === typed.trim()
}

/** Enter: the highlighted row when the rows are current, else a search for what is typed now. */
export function enterTarget(answeredFor: string, typed: string, open: boolean, active: number, count: number): number | 'search' {
  if (!rowsAreCurrent(answeredFor, typed)) return 'search'
  return open && active >= 0 && active < count ? active : 'search'
}

/** Arrow keys move through the rows and wrap; -1 is "no row" (the input itself). */
export function moveActive(active: number, delta: 1 | -1, count: number): number {
  if (count === 0) return -1
  if (active < 0) return delta === 1 ? 0 : count - 1
  return (active + delta + count) % count
}

/** Rows are ranked near the site on the map: its outline's box, widened to a few kilometres. */
export function searchBox(bounds: readonly [number, number, number, number] | null): [number, number, number, number] | null {
  if (!bounds) return null
  const pad = 0.03
  return [bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad]
}
