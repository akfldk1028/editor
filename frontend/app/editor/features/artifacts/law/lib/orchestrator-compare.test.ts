import { expect, test } from 'bun:test'

import type { RunLaw } from '@/lib/orchestrator-runs/types'

import { compareLaw, differingRows } from './orchestrator-compare'
import type { Summary } from './summary'

const law: RunLaw = {
  status: 'succeeded', site_area_m2: 2499.691, bcr_pct: 59.92, far_pct: 249.67, max_floors: 5, policy_id: 'gosan-public1-molit-2026-334',
  parcel_label: null, building_type: '업무시설', ordinance: null, sources: [], findings: [], truncated: true,
}

const editor = (over: Partial<Summary> = {}): Summary => ({
  pnu: '4115011300106840001', zones: ['일반상업지역'], otherZones: [], zoneAreas: [], overlapArticle: null,
  bcr: { limit: null, ceiling: 59.9, status: 'needs_evidence', article: '' }, far: { limit: null, ceiling: 249.7, status: 'needs_evidence', article: '' },
  areaM2: 2500, landCategory: null, officialPrice: null, restrictions: [], assessment: { label: '증거 부족', tone: 'warn', detail: [] }, assessmentDate: null,
  ...over,
})

test('the 고산 run beside the editor: same area within tolerance, editor caps unconfirmed → marked different', () => {
  const rows = compareLaw(law, editor())
  expect(rows.map((row) => row.label)).toEqual(['대지면적', '건폐율 상한', '용적률 상한', '최고 층수'])
  expect(rows[0]).toEqual({ label: '대지면적', run: '2,499.69 ㎡', editor: '2,500 ㎡', differs: false })
  expect(rows[1]).toEqual({ label: '건폐율 상한', run: '59.92%', editor: '미확정 (법정 상한 59.9%)', differs: true })
  expect(rows[2]!.run).toBe('249.67%')
  expect(rows[3]).toEqual({ label: '최고 층수', run: '5층', editor: '—', differs: null })
  expect(differingRows(rows)).toBe(2)
})

test('confirmed editor caps compare numerically; a large area gap is a difference', () => {
  const rows = compareLaw(law, editor({ bcr: { limit: 60, ceiling: 60, status: 'complete', article: 'x' }, far: { limit: 250, ceiling: 250, status: 'complete', article: 'y' }, areaM2: 2600 }))
  expect(rows[0]!.differs).toBe(true)
  expect(rows[1]).toEqual({ label: '건폐율 상한', run: '59.92%', editor: '60%', differs: true })
  expect(compareLaw({ ...law, bcr_pct: 60 }, editor({ bcr: { limit: 60, ceiling: 60, status: 'complete', article: 'x' } }))[1]!.differs).toBe(false)
})

test('missing sides are not comparable', () => {
  const rows = compareLaw(null, editor())
  expect(rows.map((row) => row.run)).toEqual(['—', '—', '—', '—'])
  expect(rows.map((row) => row.differs)).toEqual([null, null, null, null])
  expect(compareLaw(law, null)[0]).toEqual({ label: '대지면적', run: '2,499.69 ㎡', editor: '—', differs: null })
  expect(compareLaw(law, null)[1]!.editor).toBe('미확정')
})
