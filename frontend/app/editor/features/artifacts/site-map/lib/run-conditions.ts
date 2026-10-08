/** The 조건 a site run carries: 기준일 (required) and 용도 (optional). Pure; storage is passed in. */

export interface RunConditions {
  /** YYYY-MM-DD; the Orchestrator stores it on the project for Program and the 지구단위 review. */
  assessmentDate: string
  /** One of BUILDING_TYPES or '' (none). */
  buildingType: string
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
export const STORAGE_KEY = 'site-run-conditions'

/** Local calendar date, YYYY-MM-DD. */
export function today(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export const defaultRunConditions = (): RunConditions => ({ assessmentDate: today(), buildingType: '' })

/** A date the input and the backend both accept: ISO shape and a real calendar day. */
export function isValidDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

type Store = Pick<Storage, 'getItem' | 'setItem'>

/** The last used 조건, when saved and still well-formed; else the defaults. Storage failures are defaults too. */
export function loadRunConditions(storage?: Store): RunConditions {
  const defaults = defaultRunConditions()
  try {
    const raw = (storage ?? globalThis.localStorage)?.getItem(STORAGE_KEY)
    if (!raw) return defaults
    const saved = JSON.parse(raw) as Partial<RunConditions> | null
    return {
      assessmentDate: typeof saved?.assessmentDate === 'string' && isValidDate(saved.assessmentDate) ? saved.assessmentDate : defaults.assessmentDate,
      buildingType: typeof saved?.buildingType === 'string' ? saved.buildingType.slice(0, 64) : '',
    }
  } catch {
    return defaults
  }
}

export function saveRunConditions(conditions: RunConditions, storage?: Store): void {
  try {
    const store = storage ?? globalThis.localStorage
    store?.setItem(STORAGE_KEY, JSON.stringify(conditions))
  } catch {
    // Private mode or a full quota: the next run simply starts from the defaults.
  }
}
