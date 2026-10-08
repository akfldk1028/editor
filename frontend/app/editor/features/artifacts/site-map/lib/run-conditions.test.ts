import { expect, test } from 'bun:test'

import { defaultRunConditions, isValidDate, loadRunConditions, saveRunConditions, STORAGE_KEY, today } from './run-conditions'

const memory = () => {
  const map = new Map<string, string>()
  return { getItem: (key: string) => map.get(key) ?? null, setItem: (key: string, value: string) => void map.set(key, value), map }
}

test('today is a local YYYY-MM-DD and the defaults carry it with no 용도', () => {
  expect(today(new Date(2026, 9, 8, 23, 59))).toBe('2026-10-08')
  expect(defaultRunConditions()).toEqual({ assessmentDate: today(), buildingType: '' })
})

test('a valid date is ISO-shaped and a real calendar day', () => {
  expect(isValidDate('2026-10-08')).toBe(true)
  expect(isValidDate('2024-02-29')).toBe(true)
  expect(isValidDate('2025-02-29')).toBe(false)
  expect(isValidDate('2026-13-01')).toBe(false)
  expect(isValidDate('2026/10/08')).toBe(false)
  expect(isValidDate('')).toBe(false)
})

test('the last used 조건 round-trip through storage; junk and failures fall back to the defaults', () => {
  const store = memory()
  expect(loadRunConditions(store)).toEqual(defaultRunConditions())
  saveRunConditions({ assessmentDate: '2026-10-01', buildingType: '업무시설' }, store)
  expect(JSON.parse(store.map.get(STORAGE_KEY)!)).toEqual({ assessmentDate: '2026-10-01', buildingType: '업무시설' })
  expect(loadRunConditions(store)).toEqual({ assessmentDate: '2026-10-01', buildingType: '업무시설' })
  store.setItem(STORAGE_KEY, JSON.stringify({ assessmentDate: '2026-02-30', buildingType: 7 }))
  expect(loadRunConditions(store)).toEqual(defaultRunConditions())
  store.setItem(STORAGE_KEY, '{not json')
  expect(loadRunConditions(store)).toEqual(defaultRunConditions())
  expect(loadRunConditions(undefined)).toEqual(defaultRunConditions())
  const throwing = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
  expect(loadRunConditions(throwing)).toEqual(defaultRunConditions())
  expect(() => saveRunConditions(defaultRunConditions(), throwing)).not.toThrow()
})
