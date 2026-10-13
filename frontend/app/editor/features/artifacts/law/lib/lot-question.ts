import type { LotCandidate, QuotedValue, RunQuestion } from '@/lib/orchestrator-runs/types'

/** The fields Law reads for a lot, in words and in the order a reviewer reads them; values stay as Law quoted them. */
const FIELDS: ReadonlyArray<readonly [string, string, string]> = [
  ['bcr_pct_max', '건폐율', '% 이하'],
  ['far_pct_max', '용적률', '% 이하'],
  ['max_storeys', '최고층수', '층 이하'],
  ['max_height_m', '최고높이', ' m 이하'],
  ['allowed_uses', '허용 용도', ''],
  ['disallowed_uses', '불허 용도', ''],
]

export interface LotRow {
  label: string
  values: { text: string; quote: string | null; source: string | null }[]
}

export interface LotChoice {
  lot: string
  rows: LotRow[]
  /** Fields this screen has no word for: counted, never shown by their key. */
  others: number
}

const quoted = (item: unknown): QuotedValue => (item && typeof item === 'object' ? item as QuotedValue : { value: item })

function valueText(value: unknown, unit: string): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.map((item) => valueText(item, '')).join(', ')
  if (typeof value === 'object') return '(상세)'
  return `${String(value)}${unit}`
}

function row(label: string, unit: string, raw: unknown): LotRow {
  const items = Array.isArray(raw) ? raw : [raw]
  return {
    label,
    values: items.map(quoted).map((item) => ({
      text: valueText(item.value, unit),
      quote: typeof item.quote === 'string' && item.quote ? item.quote : null,
      source: [item.document, item.article].filter((part): part is string => typeof part === 'string' && !!part).join(' · ') || null,
    })),
  }
}

/** The lots a waiting run offers to choose from (Law could not tie the parcel to one); empty when it offers none. */
export function lotChoices(question: RunQuestion | null | undefined): LotChoice[] {
  const lots = question?.candidates?.lots
  if (!Array.isArray(lots)) return []
  return lots.filter((lot): lot is LotCandidate => !!lot && typeof lot.lot === 'string' && !!lot.lot).map((lot) => {
    const known = new Set(['lot', ...FIELDS.map(([key]) => key)])
    return {
      lot: lot.lot,
      rows: FIELDS.filter(([key]) => lot[key] !== undefined && lot[key] !== null).map(([key, label, unit]) => row(label, unit, lot[key])),
      others: Object.keys(lot).filter((key) => !known.has(key)).length,
    }
  })
}

/** Whether a waiting run asks which district lot the parcel is (the answer is one of the offered lots). */
export const asksForLot = (question: RunQuestion | null | undefined): boolean =>
  !!question && question.fields.includes('district_lot') && lotChoices(question).length > 0
