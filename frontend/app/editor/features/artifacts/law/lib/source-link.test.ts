import { expect, test } from 'bun:test'
import { sourceLink } from './source-link'
import type { ReviewRef } from './review'

test('source links prefer returned provenance and distinguish current-law fallback', () => {
  const ref: ReviewRef = { instrument: '갑시 주차장 조례', kind: 'ordinance', article: null, clause: null, text: null, text_status: 'needs_source' }
  expect(decodeURI(sourceLink(ref).url)).toBe('https://www.law.go.kr/자치법규/갑시주차장조례')
  expect(sourceLink(ref).label).toContain('현행')
  expect(decodeURI(sourceLink({ ...ref, kind: 'act', instrument: '건축법' }).url)).toBe('https://www.law.go.kr/법령/건축법')
  expect(sourceLink(ref, { text: '', url: 'https://www.law.go.kr/edition' })).toEqual({ url: 'https://www.law.go.kr/edition', label: '공식 원문' })
})
