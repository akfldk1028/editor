import { expect, test } from 'bun:test'

import { fixture } from './summary.fixture'
import { assessmentBadge, capOf, countArticles, countRegulations, formatCap, lotLabel, summarize } from './summary'

test('the summary carries zones, split areas largest first, land facts and the restrictions', () => {
  const summary = summarize(fixture)
  expect(summary.pnu).toBe('4115011300106840001')
  expect(summary.zones).toEqual(['제2종일반주거지역', '자연녹지지역'])
  expect(summary.otherZones).toHaveLength(5)
  expect(summary.zoneAreas.map((z) => z.zone)).toEqual(['제2종일반주거지역', '자연녹지지역'])
  expect(summary.overlapArticle).toContain('제84조')
  expect(summary.areaM2).toBe(2500)
  expect(summary.landCategory).toBe('대')
  expect(summary.officialPrice).toBe(1_660_000)
  expect(summary.restrictions).toHaveLength(3)
  expect(summary.assessmentDate).toBe('2026-10-08')
})

test('an unknown ordinance cap reads 미확정 with the statutory ceiling as a note, a known one as a percent', () => {
  const bcr = formatCap(capOf(fixture.regulations!.bcr))
  expect(bcr.value).toBe('미확정')
  expect(bcr.note).toContain('59.9%')
  expect(formatCap(capOf({ limit_pct: 60, article: 'x' }))).toEqual({ value: '60%', note: null })
  expect(formatCap(capOf(undefined))).toEqual({ value: '미확정', note: '조례 증거 확인 필요' })
})

test('the assessment badge names the status, the ordinance edition and each missing zoning', () => {
  const badge = assessmentBadge(fixture.assessment)
  expect(badge.label).toBe('증거 부족')
  expect(badge.tone).toBe('warn')
  expect(badge.detail[0]).toContain('미검증')
  expect(badge.detail).toContain('의정부시 도시계획 조례 (시행 2025-09-25)')
  expect(badge.detail).toContain('미인식 용도지역: 공공청사')
  expect(badge.detail).toContain('설계 적용성·허가 검토 미완료')
  expect(badge.detail).toHaveLength(5)
  expect(assessmentBadge(undefined)).toEqual({ label: '심사 정보 없음', tone: 'muted', detail: [] })
  expect(assessmentBadge({ status: 'verified', permit_compliance_verified: true }).tone).toBe('ok')
})

test('counts match the /land panel: core cards + extended + overlays; articles fall back to the list', () => {
  expect(countRegulations(fixture)).toBe(10 + 2 + 3)
  expect(countArticles(fixture)).toBe(0)
  expect(countArticles({ ...fixture, law_articles: { articles: [{ hang_id: 'a', content: 'x' }] } })).toBe(1)
  expect(countRegulations({ ...fixture, regulations: null, overlay_regulations: undefined })).toBe(0)
})

test('lot labels come from the address tail, else from the PNU', () => {
  expect(lotLabel('경기도 의정부시 산곡동 684-1', '4115011300106840001')).toBe('684-1')
  expect(lotLabel('', '4115011300106840001')).toBe('684-1')
  expect(lotLabel('', '4115011300206840000')).toBe('산684')
})
