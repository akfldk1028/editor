import { expect, test } from 'bun:test'

import { chooseEngine } from './engine'
import { boundsCenter, parcelBounds, parcelRings } from './layers/parcelOutline'
import { siteFromParams, siteFromSelection, siteParam } from './site'

test('engine: naver with a key, openlayers without, ?engine=openlayers always wins', () => {
  expect(chooseEngine(undefined, 'key')).toBe('naver')
  expect(chooseEngine(undefined, undefined)).toBe('openlayers')
  expect(chooseEngine(undefined, '')).toBe('openlayers')
  expect(chooseEngine('openlayers', 'key')).toBe('openlayers')
  expect(chooseEngine('naver', undefined)).toBe('openlayers')
  expect(chooseEngine('naver', 'key')).toBe('naver')
})

test('parcel rings come out of polygons, multipolygons, features and collections', () => {
  const square = [[[127, 37], [127.001, 37], [127.001, 37.001], [127, 37]]]
  expect(parcelRings({ type: 'Polygon', coordinates: square })).toHaveLength(1)
  expect(parcelRings({ type: 'MultiPolygon', coordinates: [square, square] })).toHaveLength(2)
  expect(parcelRings({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: square } }] })).toHaveLength(1)
  expect(parcelRings({ type: 'Point', coordinates: [127, 37] })).toEqual([])
  expect(parcelRings(null)).toEqual([])
  const bounds = parcelBounds(parcelRings({ type: 'Polygon', coordinates: square }))
  expect(bounds).toEqual([127, 37, 127.001, 37.001])
  expect(boundsCenter(bounds!)).toEqual([127.0005, 37.0005])
  expect(parcelBounds([])).toBeNull()
})

test('the site defaults to 고산 공공1 and takes a PNU or address from the shell params', () => {
  expect(siteFromParams({})).toEqual({ query: '4115011300106840001', label: '고산 공공1 · 경기도 의정부시 산곡동 684-1' })
  expect(siteFromParams({ pnu: '1168010100107370000' })).toEqual({ query: '1168010100107370000', label: '1168010100107370000' })
  expect(siteFromParams({ address: '서울 강남구 역삼동 737' }).query).toBe('서울 강남구 역삼동 737')
  expect(siteFromParams({ pnu: '12' }).query).toBe('4115011300106840001')
})

test('an explicit pnu/address param is the only thing that beats the saved selection', () => {
  expect(siteParam({})).toBeNull()
  expect(siteParam({ pnu: '12' })).toBeNull()
  expect(siteParam({ pnu: '1168010100107370000' })?.query).toBe('1168010100107370000')
  expect(siteFromSelection({ pnu: '4115011300106840001', address: '경기도 의정부시 산곡동 684-1' }))
    .toEqual({ query: '4115011300106840001', label: '경기도 의정부시 산곡동 684-1' })
  expect(siteFromSelection({ pnu: '4115011300106840001', address: '' }).label).toBe('4115011300106840001')
})

test('picks: a click selects that parcel alone, adding toggles in order, clicking the only pick deselects it', async () => {
  const { nextPicks } = await import('./picks')
  const a = { pnu: 'a', at: [127, 37] as const }
  const b = { pnu: 'b', at: [127.1, 37] as const }
  const c = { pnu: 'c', at: [127.2, 37] as const }
  expect(nextPicks([], a, false)).toEqual([a])
  expect(nextPicks([a], b, false)).toEqual([b])
  // A plain click on a parcel inside a bundle keeps only that parcel.
  expect(nextPicks([a, b, c], b, false)).toEqual([b])
  // A plain click on the only selected parcel deselects it.
  expect(nextPicks([a], a, false)).toEqual([])
  // Adding appends or removes, keeping the order.
  expect(nextPicks([a], b, true)).toEqual([a, b])
  expect(nextPicks([a, b, c], b, true)).toEqual([a, c])
  expect(nextPicks([a], a, true)).toEqual([])
})

test("the selection scope is the shell's ?project=, else default", async () => {
  const { selectionScope } = await import('./picks')
  expect(selectionScope({})).toBe('default')
  expect(selectionScope({ project: 'gosan-1' })).toBe('gosan-1')
  expect(selectionScope({ project: 'a b' })).toBe('default')
  expect(selectionScope({ project: 'x'.repeat(65) })).toBe('default')
})

test('parcel looks, point-in-parcel, lot labels and the hover cache', async () => {
  const { containsPoint, lotLabel, parcelStyle } = await import('./layers/parcelOutline')
  const { ParcelCache } = await import('../model/parcelCache')
  expect(parcelStyle('site')).toEqual({ width: 2.5, dashed: true, fillOpacity: 0 })
  expect(parcelStyle('picked')).toEqual({ width: 2, dashed: true, fillOpacity: 0.15 })
  expect(parcelStyle('saved')).toEqual({ width: 2, dashed: false, fillOpacity: 0.22 })
  const square = { type: 'Polygon', coordinates: [[[127, 37], [127.001, 37], [127.001, 37.001], [127, 37.001], [127, 37]]] }
  expect(containsPoint(square, [127.0005, 37.0005])).toBe(true)
  expect(containsPoint(square, [127.002, 37.0005])).toBe(false)
  expect(lotLabel('경기도 의정부시 산곡동 684-1', '4115011300106840001')).toBe('684-1')
  expect(lotLabel('', '4115011300206840000')).toBe('산684')
  expect(lotLabel('경기도 의정부시 민락동 산 98-17', '4115010600200980017')).toBe('산98-17')
  const cache = new ParcelCache(2)
  cache.add({ pnu: 'a', address: '', geometry: square })
  expect(cache.find([127.0005, 37.0005])?.pnu).toBe('a')
  expect(cache.find([128, 38])).toBeNull()
  cache.add({ pnu: 'b', address: '', geometry: {} })
  cache.add({ pnu: 'c', address: '', geometry: {} })
  expect(cache.get('a')).toBeNull()
})
