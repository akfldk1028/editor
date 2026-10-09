/**
 * The Law Agent's review list for the lot (`analysis.review`, built by the backend from the calculators and the
 * overlay table). Shown as it comes: the screen groups and labels it, never re-judges a status.
 */

export type ReviewStatus = 'applies' | 'conditional' | 'needs_check' | 'needs_source'

export interface ReviewRef {
  instrument: string
  kind: 'act' | 'decree' | 'rule' | 'ordinance'
  article: string | null
  clause: string | null
  text: string | null
  text_status: 'found' | 'needs_source'
  text_gap?: string
  hang_ids?: string[]
  url?: string
  edition_id?: string
  effective_date?: string
}

export interface ReviewItem {
  id: string
  group: string
  title: string
  refs: ReviewRef[]
  reason: string
  status: ReviewStatus
  basis: string
  value: string | null
}

export interface Review {
  assessment_date: string | null
  groups: { id: string; label: string }[]
  items: ReviewItem[]
  gaps: { item: string | null; what: string }[]
  search: { connected: boolean | null; errors: string[] }
}

export const STATUS_LABEL: Record<ReviewStatus, string> = {
  applies: '적용 확인',
  conditional: '조건부 적용',
  needs_check: '적용 여부 확인 필요',
  needs_source: '자료 확보 필요',
}

export const KIND_LABEL: Record<ReviewRef['kind'], string> = { act: '법률', decree: '시행령', rule: '시행규칙', ordinance: '조례' }

/** "건축법 제61조제1항" */
export const refLabel = (ref: Pick<ReviewRef, 'instrument' | 'article' | 'clause'>): string =>
  [ref.instrument, ref.article, ref.clause].filter(Boolean).join(' ')

/** The groups in the backend's order, each with its items; a group the lot has nothing in is left out. */
export function grouped(review: Review): { id: string; label: string; items: ReviewItem[] }[] {
  return review.groups
    .map((group) => ({ ...group, items: review.items.filter((item) => item.group === group.id) }))
    .filter((group) => group.items.length > 0)
}

/** Counts per status, for the header line ("적용 확인 6 · 조건부 5 · …"); nothing is called "applicable laws". */
export function statusCounts(review: Review): { status: ReviewStatus; count: number }[] {
  return (Object.keys(STATUS_LABEL) as ReviewStatus[])
    .map((status) => ({ status, count: review.items.filter((item) => item.status === status).length }))
    .filter((entry) => entry.count > 0)
}

/** 20250925 → 2025-09-25 */
export const ymd = (value: string | undefined): string | null =>
  !value ? null : /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : value

/** What the conversation carries when the user asks about one item. */
export function clauseContext(item: ReviewItem) {
  return {
    item_id: item.id,
    title: item.title,
    refs: item.refs.map(({ instrument, kind, article, clause, hang_ids, edition_id }) => ({
      instrument, kind, article, clause, ...(hang_ids?.[0] ? { hang_id: hang_ids[0] } : {}), ...(edition_id ? { edition_id } : {}) })),
    reason: item.reason.slice(0, 400),
    status: item.status,
    basis: item.basis.slice(0, 400),
  }
}
