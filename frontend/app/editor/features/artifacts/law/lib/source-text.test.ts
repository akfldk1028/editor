import { expect, test } from 'bun:test'
import { sourceParagraphs, sourceUnit } from './source-text'

test('source paragraphs separate numbered provisions without splitting amendment dates or dropping text', () => {
  const text = '제1조(기준) <개정 2025.9.25>1. 첫 항목2. 다음 항목①첫 항②둘째 항'
  const parts = sourceParagraphs(text)
  expect(parts).toHaveLength(5)
  expect(parts[0]).toContain('2025.9.25')
  expect(parts.join('').replace(/\s/g, '')).toBe(text.replace(/\s/g, ''))
})

test('legal hierarchy retains paragraph, numbered item and lettered subitem text', () => {
  const text = '① 적용 범위\n1. 건축물\n가. 주거용\n나. 업무용'
  const parts = sourceParagraphs(text)
  expect(parts.map(sourceUnit)).toEqual(['paragraph', 'item', 'subitem', 'subitem'])
  expect(parts.join('').replace(/\s/g, '')).toBe(text.replace(/\s/g, ''))
})
