import type { LotCandidate, QuotedValue, RunQuestion } from '@/lib/orchestrator-runs/types'

/** The fields Law reads for a lot, in words and in the order a reviewer reads them; values stay as Law quoted them. */
const FIELDS: ReadonlyArray<readonly [string, string, string]> = [
  ['bcr_pct_max', '건폐율', '% 이하'],
  ['far_pct_max', '용적률', '% 이하'],
  ['max_storeys', '최고층수', '층 이하'],
  ['max_height_m', '최고높이', ' m 이하'],
  ['building_line_m', '건축한계선', ' m'],
  ['allowed_uses', '허용 용도', ''],
  ['disallowed_uses', '불허 용도', ''],
]

export interface LotRow {
  label: string
  values: { text: string; quote: string | null; source: string | null }[]
}

export interface LotChoice {
  lot: string
  /** Where the documents name this lot, as quoted. */
  basis: { quote: string | null; source: string | null } | null
  rows: LotRow[]
  /** Fields this screen has no word for: counted, never shown by their key. */
  others: number
}

const quoted = (item: unknown): QuotedValue & { text?: string | null } => (item && typeof item === 'object' ? item as QuotedValue : { value: item })

/** A source as a person reads it: the document's file name (never a server path) and the article. */
function sourceOf(item: { document?: string; article?: string }): string | null {
  const name = typeof item.document === 'string' ? item.document.split(/[\\/]/).pop() || null : null
  return [name, item.article].filter((part): part is string => typeof part === 'string' && !!part).join(' · ') || null
}

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
    values: items.map(quoted).map((item) => {
      // A figure reads with its unit and what it is measured from ("8 m (중로 2-54, 55호선변)"); a use list is its text.
      const words = typeof item.text === 'string' && item.text ? item.text : null
      const figure = item.value !== null && item.value !== undefined ? valueText(item.value, unit) : null
      return {
        text: figure && words ? `${figure} (${words})` : figure ?? words ?? '—',
        quote: typeof item.quote === 'string' && item.quote ? item.quote : null,
        source: sourceOf(item),
      }
    }),
  }
}

/** The lots a waiting run offers to choose from (Law could not tie the parcel to one); empty when it offers none. */
export function lotChoices(question: RunQuestion | null | undefined): LotChoice[] {
  const lots = question?.candidates?.lots
  if (!Array.isArray(lots)) return []
  return lots.filter((lot): lot is LotCandidate => !!lot && typeof lot.lot === 'string' && !!lot.lot).map((lot) => {
    const known = new Set(['lot', 'lot_basis', ...FIELDS.map(([key]) => key)])
    const basis = lot.lot_basis && typeof lot.lot_basis === 'object' ? lot.lot_basis as { quote?: string; document?: string; article?: string } : null
    return {
      lot: lot.lot,
      basis: basis ? { quote: typeof basis.quote === 'string' ? basis.quote : null, source: sourceOf(basis) } : null,
      rows: FIELDS.filter(([key]) => lot[key] !== undefined && lot[key] !== null).map(([key, label, unit]) => row(label, unit, lot[key])),
      others: Object.keys(lot).filter((key) => !known.has(key)).length,
    }
  })
}

/** Whether a waiting run asks which district lot the parcel is (the answer is one of the offered lots). */
export const asksForLot = (question: RunQuestion | null | undefined): boolean =>
  !!question && question.fields.includes('district_lot') && lotChoices(question).length > 0
