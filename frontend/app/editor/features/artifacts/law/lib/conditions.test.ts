import { expect, test } from 'bun:test'

import { cacheKey, defaultConditions, describeConditions, parseArea, today } from './conditions'

test('today is a local YYYY-MM-DD and the default 조건 carry only it', () => {
  expect(today(new Date(2026, 9, 8, 23, 59))).toBe('2026-10-08')
  expect(today(new Date(2026, 0, 1, 0, 0))).toBe('2026-01-01')
  expect(defaultConditions()).toEqual({ buildingType: '', floorAreaM2: null, assessmentDate: today() })
})

test('the cache key changes with every 조건 and the subtitle names only the set ones', () => {
  const base = { buildingType: '', floorAreaM2: null, assessmentDate: '2026-10-08' }
  expect(cacheKey('p', base)).toBe('p|||2026-10-08')
  expect(cacheKey('p', { ...base, buildingType: ' 업무시설 ' })).toBe('p|업무시설||2026-10-08')
  expect(cacheKey('p', { ...base, floorAreaM2: 5000 })).not.toBe(cacheKey('p', base))
  expect(describeConditions(base)).toBe('기준일 2026-10-08')
  expect(describeConditions({ buildingType: '업무시설', floorAreaM2: 5000, assessmentDate: '2026-10-08' })).toBe('업무시설 · 연면적 5,000 ㎡ · 기준일 2026-10-08')
})

test('a typed 연면적 accepts separators and units, and rejects empty, zero and junk', () => {
  expect(parseArea('5,000')).toBe(5000)
  expect(parseArea(' 1 200.5 ㎡')).toBe(1200.5)
  expect(parseArea('')).toBeNull()
  expect(parseArea('0')).toBeNull()
  expect(parseArea('abc')).toBeNull()
})
