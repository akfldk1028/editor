import { expect, test } from 'bun:test'

import { cadastralImageUrl, toMercator } from './cadastralTiles'

test('toMercator maps lon/lat to EPSG:3857 metres', () => {
  expect(toMercator(0, 0)).toEqual([0, 0])
  const [x, y] = toMercator(127.1112, 37.7343)
  expect(x).toBeCloseTo(14149986.6, 0)
  expect(y).toBeCloseTo(4542040, -2)
})

test('cadastralImageUrl asks the proxy for one transparent image of the view, clamped to 2048 px a side', () => {
  const url = new URL(cadastralImageUrl(127.11, 37.733, 127.113, 37.735, 1200, 800, 'http://127.0.0.1:3003/api/v1/land/wms', 'lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun'))
  expect(url.pathname).toBe('/api/v1/land/wms')
  expect(url.searchParams.get('CRS')).toBe('EPSG:3857')
  expect(url.searchParams.get('LAYERS')).toBe('lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun')
  expect([url.searchParams.get('WIDTH'), url.searchParams.get('HEIGHT')]).toEqual(['1200', '800'])
  const [minX, minY, maxX, maxY] = url.searchParams.get('BBOX')!.split(',').map(Number)
  expect(minX).toBeLessThan(maxX)
  expect(minY).toBeLessThan(maxY)
  const big = new URL(cadastralImageUrl(127, 37, 128, 38, 4096, 1024, 'http://x/w', 'l'))
  expect([big.searchParams.get('WIDTH'), big.searchParams.get('HEIGHT')]).toEqual(['2048', '512'])
})
