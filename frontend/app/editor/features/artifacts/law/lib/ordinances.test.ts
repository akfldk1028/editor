import { expect, test } from 'bun:test'
import type { DiscoveredOrdinance, OrdinanceDiscovery } from '../api/ordinances'
import { articlesOf, citedOrdinances, jurisdictionLine, ordinanceLine, searchSummary, toReviewItem, toReviewRef } from './ordinances'
import type { Review } from './review'

const ordinance: DiscoveredOrdinance = {
  name: '을시 도시계획 조례', kind: '조례', ordinance_id: 'A', edition_id: '2001', effective_date: '2025-09-25', promulgated: '2025-09-25', promulgation_no: '1',
  revision: '일부개정', issuer: '갑도 을시', detail_url: null, level: 'sigungu', url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2001', editions_seen: 1, future_editions: [],
  status: { jurisdiction: 'verified', edition: 'dated', body: 'not_fetched', in_force: 'current', relevance: 'exact' },
  review_refs: [
    { item_id: 'bcr-cap', title: '건폐율 상한', article: '제42조', status: 'applies', match: 'exact' },
    { item_id: 'far-cap', title: '용적률 상한', article: '제46조', status: 'applies', match: 'exact' },
    { item_id: 'x', title: 'x', article: '제42조', status: null, match: 'exact' },
  ],
  topics: ['도시계획'],
}

const review: Review = {
  assessment_date: '2026-10-09', groups: [{ id: 'bcr_far', label: '건폐율·용적률' }], gaps: [], search: { connected: true, errors: [] },
  items: [
    { id: 'bcr-cap', group: 'bcr_far', title: '건폐율 상한', reason: '', status: 'applies', basis: '', value: '60%', refs: [
      { instrument: '국토의 계획 및 이용에 관한 법률', kind: 'act', article: '제77조', clause: null, text: null, text_status: 'needs_source' },
      { instrument: '을시 도시계획 조례', kind: 'ordinance', article: '제42조', clause: null, text: null, text_status: 'needs_source' }] },
    { id: 'parking', group: 'bcr_far', title: '주차', reason: '', status: 'conditional', basis: '', value: null, refs: [
      { instrument: '을시 도시계획 조례', kind: 'ordinance', article: '제42조', clause: null, text: null, text_status: 'needs_source' },
      { instrument: '을시 주차장 조례', kind: 'ordinance', article: null, clause: null, text: null, text_status: 'needs_source' }] },
  ],
}

test('cited ordinances are the review ordinance references once each, with their item', () => {
  expect(citedOrdinances(review)).toEqual([
    { instrument: '을시 도시계획 조례', item_id: 'bcr-cap', title: '건폐율 상한', article: '제42조', status: 'applies' },
    { instrument: '을시 주차장 조례', item_id: 'parking', title: '주차', article: null, status: 'conditional' },
  ])
})

test('a found ordinance opens as a verified reference and reads as a non-verdict item', () => {
  expect(toReviewRef(ordinance, '제42조')).toEqual({
    instrument: '을시 도시계획 조례', kind: 'ordinance', article: '제42조', clause: null, text: null, text_status: 'needs_source',
    url: ordinance.url, edition_id: '2001', effective_date: '2025-09-25',
  })
  const item = toReviewItem(ordinance, null)
  expect(item.status).toBe('needs_check')
  expect(item.basis).toBe('갑도 을시 · 시행 2025-09-25 · 판본 2001')
  expect(articlesOf(ordinance)).toEqual(['제42조', '제46조'])
  expect(ordinanceLine(ordinance)).toBe('조례 · 시행 2025-09-25 · 검토 근거 · 검토 3건')
  expect(ordinanceLine({ ...ordinance, review_refs: [], status: { ...ordinance.status, relevance: 'topic', in_force: 'unknown' } }))
    .toBe('조례 · 시행 2025-09-25 · 관련 주제 · 연혁에만 있음 · 폐지 여부 미확인')
})

test('jurisdiction and search lines say what was settled and what was not', () => {
  const base: OrdinanceDiscovery = {
    pnu: 'p', assessment_date: '2026-10-09', topics: [], ordinances: [], excluded: [], coverage_complete: false,
    jurisdiction: { address: '갑도 을시 정동 1', status: 'resolved', reason: null, notes: [], levels: [{ level: 'sido', name: '갑도', issuer: '갑도' }, { level: 'sigungu', name: '을시', issuer: '갑도 을시' }] },
    search: {
      queries: [
        { level: 'sido', issuer: '갑도', query: 'q', edition_set: 'current', complete: true },
        { level: 'sigungu', issuer: '갑도 을시', query: 'q2', edition_set: 'current', complete: false, error: 'down' },
      ],
      complete: false, other_results: 0, errors: ['q2 (current): down'],
    },
  }
  expect(jurisdictionLine(base)).toBe('갑도 · 을시 — 등기 주소 기준')
  expect(searchSummary(base)).toBe('법제처 검색 2건 · 일부 미완료 1건')
  expect(searchSummary({ ...base, search: { ...base.search, complete: true, errors: [] } })).toBe('법제처 검색 2건 · 모든 페이지 조회')
  expect(jurisdictionLine({ ...base, jurisdiction: { ...base.jurisdiction, status: 'conflict' } })).toContain('불일치')
  expect(jurisdictionLine({ ...base, error: 'law_oc_not_configured', jurisdiction: { ...base.jurisdiction, status: 'unresolved' } })).toContain('설정')
  expect(searchSummary({ ...base, search: { queries: [], complete: false, other_results: 0 } })).toBe('검색하지 않았어요')
})
