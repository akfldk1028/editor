import { expect, test } from 'bun:test'

import { chooseEngine } from './engine'
import { boundsCenter, parcelBounds, parcelRings } from './layers/parcelOutline'
import { siteFromParams } from './site'

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
