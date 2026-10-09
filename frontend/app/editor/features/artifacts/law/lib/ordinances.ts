/** Pure helpers over the discovered ordinance list: what the review cites, how a found ordinance reads, labels. */
import type { DiscoveredOrdinance, OrdinanceDiscovery, OrdinanceRefInput } from '../api/ordinances'
import type { Review, ReviewItem, ReviewRef } from './review'

/** The ordinance references the review carries, one per (instrument, article), with the item they belong to. */
export function citedOrdinances(review: Review): OrdinanceRefInput[] {
  const seen = new Set<string>()
  const out: OrdinanceRefInput[] = []
  for (const item of review.items) {
    for (const ref of item.refs) {
      if (ref.kind !== 'ordinance') continue
      const key = `${ref.instrument.replace(/\s/g, '')}|${ref.article ?? ''}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ instrument: ref.instrument, item_id: item.id, title: item.title, article: ref.article, status: item.status })
    }
  }
  return out
}

/** A found ordinance as a reference the source reader can open: its verified name, edition and official URL. */
export function toReviewRef(ordinance: DiscoveredOrdinance, article: string | null): ReviewRef {
  return {
    instrument: ordinance.name, kind: 'ordinance', article, clause: null, text: null, text_status: 'needs_source',
    url: ordinance.url, edition_id: ordinance.edition_id, ...(ordinance.effective_date ? { effective_date: ordinance.effective_date } : {}),
  }
}

/** The review item the conversation carries when a found ordinance is asked about (it is not a review verdict). */
export function toReviewItem(ordinance: DiscoveredOrdinance, article: string | null): ReviewItem {
  return {
    id: `ordinance-${ordinance.edition_id}`, group: 'ordinance', title: ordinance.name, refs: [toReviewRef(ordinance, article)],
    reason: '관할 조례 목록에서 고른 조례예요 — 적용 여부는 아직 판정되지 않았어요', status: 'needs_check',
    basis: [ordinance.issuer, ordinance.effective_date ? `시행 ${ordinance.effective_date}` : null, `판본 ${ordinance.edition_id}`].filter(Boolean).join(' · '),
    value: null,
  }
}

/** The articles the review cites in this ordinance, each once, in the review's order. */
export function articlesOf(ordinance: DiscoveredOrdinance): string[] {
  return [...new Set(ordinance.review_refs.map((ref) => ref.article).filter((article): article is string => Boolean(article)))]
}

export const LEVEL_LABEL: Record<DiscoveredOrdinance['level'], string> = { sido: '시·도', sigungu: '시·군·구' }
export const RELEVANCE_LABEL: Record<DiscoveredOrdinance['status']['relevance'], string> = { exact: '검토 근거', topic: '관련 주제' }

/** One line under a found ordinance's name: kind, effective date, why it is listed, how many review items cite it. */
export function ordinanceLine(ordinance: DiscoveredOrdinance): string {
  const parts = [ordinance.kind ?? '자치법규', ordinance.effective_date ? `시행 ${ordinance.effective_date}` : '시행일 미상', RELEVANCE_LABEL[ordinance.status.relevance]]
  if (ordinance.status.in_force === 'unknown') parts.push('연혁에만 있음 · 폐지 여부 미확인')
  if (ordinance.review_refs.length) parts.push(`검토 ${ordinance.review_refs.length}건`)
  return parts.join(' · ')
}

/** "경기도 · 의정부시 — 등기 주소 기준" or why the governments could not be settled. */
export function jurisdictionLine(discovery: OrdinanceDiscovery): string {
  const place = discovery.jurisdiction
  if (place.status === 'resolved') return `${place.levels.map((level) => level.name).join(' · ')} — 등기 주소 기준`
  if (place.status === 'conflict') return '관할 확인 불일치 — 주소와 보관 조례 자료가 다른 지자체를 가리켜 검색하지 않았어요'
  if (discovery.error === 'law_oc_not_configured') return '법제처 조회 설정이 없어 검색하지 못했어요'
  return '필지 주소를 확인하지 못해 관할을 정하지 못했어요'
}

/** "법제처 검색 16건 · 모든 페이지 조회" / "일부 실패 2건" — the search's own completeness, never legal coverage. */
export function searchSummary(discovery: OrdinanceDiscovery): string {
  const { queries, complete, errors } = discovery.search
  if (!queries.length) return '검색하지 않았어요'
  const failed = errors?.length ?? queries.filter((query) => query.error).length
  return `법제처 검색 ${queries.length}건 · ${complete ? '모든 페이지 조회' : `일부 미완료 ${failed}건`}`
}
