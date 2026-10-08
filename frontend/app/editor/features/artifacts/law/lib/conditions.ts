/** The 조건 form's values and their request/cache/subtitle forms. Pure. */

export interface Conditions {
  buildingType: string
  floorAreaM2: number | null
  /** YYYY-MM-DD; the backend defaults to today when empty. */
  assessmentDate: string
}

/** The short list in the select; anything else goes through 직접 입력. */
export const BUILDING_TYPES: readonly string[] = [
  '단독주택', '공동주택', '제1종근린생활시설', '제2종근린생활시설', '업무시설', '공공청사',
  '교육연구시설', '노유자시설', '판매시설', '숙박시설', '의료시설', '공장', '창고시설',
]

/** Local calendar date, YYYY-MM-DD. */
export function today(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export const defaultConditions = (): Conditions => ({ buildingType: '', floorAreaM2: null, assessmentDate: today() })

/** One analysis per parcel and 조건 set. */
export const cacheKey = (pnu: string, c: Conditions) => `${pnu}|${c.buildingType.trim()}|${c.floorAreaM2 ?? ''}|${c.assessmentDate}`

/** Header subtitle: "업무시설 · 연면적 5,000 ㎡ · 기준일 2026-10-08". */
export function describeConditions(c: Conditions): string {
  const parts: string[] = []
  if (c.buildingType.trim()) parts.push(c.buildingType.trim())
  if (c.floorAreaM2 != null && c.floorAreaM2 > 0) parts.push(`연면적 ${c.floorAreaM2.toLocaleString('ko-KR')} ㎡`)
  parts.push(`기준일 ${c.assessmentDate || today()}`)
  return parts.join(' · ')
}

/** A typed 연면적: digits with optional separators; null for empty, NaN-free. */
export function parseArea(text: string): number | null {
  const value = Number(text.replace(/[,\s㎡m²]/g, ''))
  return text.trim() && Number.isFinite(value) && value > 0 ? value : null
}
