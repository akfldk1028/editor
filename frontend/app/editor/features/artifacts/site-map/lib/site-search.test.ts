import { expect, test } from 'bun:test'

import type { SearchCandidate, SearchResult } from '../../../land-map/lib/land-api-client'
import { isPnu, pnuDigits } from '../../../land-map/lib/constants'
import { chosenPicks } from './picks'
import { candidateDetail, enterAction, enterTarget, moveActive, rowsAreCurrent, searchBox, searchNotice, shouldSearch } from './site-search'

const lot = (over: Partial<SearchCandidate> = {}): SearchCandidate => ({
  pnu: '4115011300106840001', kind: 'lot', jibun: '경기도 의정부시 산곡동 684-1', road: null,
  label: '경기도 의정부시 산곡동 684-1', point: [127.108, 37.73], exact: true, ...over,
})
const result = (status: SearchResult['status'], candidates: SearchCandidate[], over: Partial<SearchResult> = {}): SearchResult =>
  ({ status, normalized: 'q', kind: 'lot', candidates, ...over })

test('isPnu takes hyphens and spaces and checks the 산 digit', () => {
  expect(isPnu('4115011300106840001')).toBe(true)
  expect(isPnu(' 41150-11300-1-0684-0001 ')).toBe(true)
  expect(isPnu('4115011300206840001')).toBe(true)
  expect(isPnu('4115011300306840001')).toBe(false)
  expect(isPnu('411501130010684000')).toBe(false)
  expect(isPnu('산곡동 684-1')).toBe(false)
  expect(pnuDigits('41150-11300-1-0684-0001')).toBe('4115011300106840001')
  expect(pnuDigits('41150-11300-1-0684-000x')).toBeNull()
})

test('typing searches from two characters', () => {
  expect(shouldSearch('산')).toBe(false)
  expect(shouldSearch(' 산곡 ')).toBe(true)
})

test('Enter opens a unique parcel, zooms to a single area, and otherwise leaves the list to choose from', () => {
  expect(enterAction(result('unique', [lot()]))).toEqual({ kind: 'select', candidate: lot() })
  const area: SearchCandidate = { kind: 'area', jibun: null, road: null, label: '대구광역시 수성구 범어동', point: [128.6, 35.8], exact: true }
  expect(enterAction(result('ambiguous', [area], { kind: 'area' }))).toEqual({ kind: 'zoom', candidate: area })
  expect(enterAction(result('ambiguous', [lot(), lot({ pnu: '2823710300101000000' })]))).toEqual({ kind: 'list' })
  expect(enterAction(result('none', []))).toEqual({ kind: 'list' })
})

test('the notice says when the typed lot was replaced, or that several places share it', () => {
  const near = lot({ exact: false, substituted: true, label: '서울특별시 종로구 청운동 산 1-1' })
  expect(searchNotice(result('ambiguous', [near]))).toBe('입력한 지번은 없고 가장 가까운 서울특별시 종로구 청운동 산 1-1 입니다')
  expect(searchNotice(result('ambiguous', [lot(), lot({ pnu: 'x' })]))).toBe('같은 번지가 2곳에 있어요 — 골라 주세요')
  expect(searchNotice(result('unique', [lot()]))).toBeNull()
  expect(searchNotice(result('unavailable', [], { error: '오늘 브이월드 검색 한도를 넘었어요.' }))).toBe('오늘 브이월드 검색 한도를 넘었어요.')
})

test('a row shows the road address of a lot and the lot of a road address or place', () => {
  expect(candidateDetail(lot({ road: '을지로 42' }))).toBe('을지로 42')
  expect(candidateDetail(lot({ kind: 'road', jibun: '역삼동 858', road: '서울특별시 강남구 강남대로 396' }))).toBe('역삼동 858')
  expect(candidateDetail({ kind: 'area', jibun: null, road: null, label: 'x', point: [0, 0], exact: false })).toBeNull()
})

test('arrow keys wrap through the rows', () => {
  expect(moveActive(-1, 1, 3)).toBe(0)
  expect(moveActive(-1, -1, 3)).toBe(2)
  expect(moveActive(2, 1, 3)).toBe(0)
  expect(moveActive(0, -1, 3)).toBe(2)
  expect(moveActive(0, 1, 0)).toBe(-1)
})

test('the search box is the site outline widened', () => {
  expect(searchBox(null)).toBeNull()
  const box = searchBox([127, 37, 127.01, 37.01])!
  ;[126.97, 36.97, 127.04, 37.04].forEach((value, index) => expect(box[index]).toBeCloseTo(value, 9))
})

test('rows of an older text are never chosen: Enter searches the text typed now', () => {
  expect(rowsAreCurrent('신촌동 1', ' 신촌동 1 ')).toBe(true)
  expect(rowsAreCurrent('신촌동 1', '신촌동 10')).toBe(false)
  expect(enterTarget('신촌동 1', '신촌동 1', true, 1, 5)).toBe(1)
  expect(enterTarget('신촌동 1', '신촌동 10', true, 1, 5)).toBe('search')
  expect(enterTarget('신촌동 1', '신촌동 1', false, 1, 5)).toBe('search')
  expect(enterTarget('신촌동 1', '신촌동 1', true, 7, 5)).toBe('search')
})

test('a parcel chosen by name joins the bundle in add mode and replaces it otherwise', () => {
  const a = { pnu: 'a', at: [1, 1] as const }
  const b = { pnu: 'b', at: [2, 2] as const }
  expect(chosenPicks([a], b, false)).toEqual([b])
  expect(chosenPicks([a], a, false)).toEqual([a])
  expect(chosenPicks([a], b, true)).toEqual([a, b])
  expect(chosenPicks([a, b], b, true)).toEqual([a, b])
})

test('a PNU typed with spaces is a PNU and goes as its digits', () => {
  expect(isPnu('41150 11300 1 0684 0001')).toBe(true)
  expect(pnuDigits('41150 11300 1 0684 0001')).toBe('4115011300106840001')
})
