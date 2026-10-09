import { expect, test } from 'bun:test'

import { clauseContext, grouped, refLabel, type Review, statusCounts, ymd } from './review'

const review: Review = {
  assessment_date: '2026-10-09',
  groups: [{ id: 'use', label: '용도 제한' }, { id: 'bcr_far', label: '건폐율·용적률' }, { id: 'district', label: '지역·지구·지구단위계획' }],
  items: [
    { id: 'use-zone', group: 'use', title: '용도지역 안에서의 건축 제한', refs: [{ instrument: '국토의 계획 및 이용에 관한 법률', kind: 'act', article: '제76조', clause: null, text: '원문', text_status: 'found' }], reason: 'r', status: 'conditional', basis: 'b', value: null },
    { id: 'district-공공주택지구', group: 'district', title: '공공주택지구', refs: [], reason: 'r', status: 'needs_source', basis: '지구계획 필요', value: null },
  ],
  gaps: [{ item: 'district-공공주택지구', what: '지구계획 필요' }],
  search: { connected: true, errors: [] },
}

test('groups keep the backend order and drop empty ones; counts are per status, not "applicable laws"', () => {
  expect(grouped(review).map((group) => [group.id, group.items.length])).toEqual([['use', 1], ['district', 1]])
  expect(statusCounts(review)).toEqual([{ status: 'conditional', count: 1 }, { status: 'needs_source', count: 1 }])
})

test('labels, dates and the clause context the conversation carries', () => {
  expect(refLabel({ instrument: '건축법', article: '제61조', clause: '제1항' })).toBe('건축법 제61조 제1항')
  expect(ymd('20250925')).toBe('2025-09-25')
  expect(ymd(undefined)).toBeNull()
  expect(clauseContext(review.items[0]!)).toEqual({ item_id: 'use-zone', title: '용도지역 안에서의 건축 제한',
    refs: [{ instrument: '국토의 계획 및 이용에 관한 법률', kind: 'act', article: '제76조', clause: null }], reason: 'r', status: 'conditional', basis: 'b' })
})
