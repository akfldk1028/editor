import { expect, test } from 'bun:test'
import { lodTiles } from './building-lod'
import { tileXY, tilesOverlap } from './building-geometry'

const box: [number, number, number, number] = [126.97, 37.48, 127.15, 37.7]
test('LOD refines nearby tiles while retaining coarse distant coverage without overlapping levels', () => {
  const tiles = lodTiles(box, { lon: 127, lat: 37.5 }, { lon: 127, lat: 37.49, height: 400, pixels: 900, fov: 1 })
  expect(new Set(tiles.map(t => t.z)).size).toBeGreaterThan(1)
  const levelAt = (lon: number, lat: number) => tiles.find(t => { const [x, y] = tileXY(lon, lat, t.z); return x === t.x && y === t.y })?.z
  expect(levelAt(127, 37.5)).toBe(16)
  expect(levelAt(127.14, 37.69)).toBeLessThan(16)
  expect(tiles.length).toBeLessThanOrEqual(96)
  for (let i = 0; i < tiles.length; i++) for (let j = i + 1; j < tiles.length; j++) expect(tilesOverlap(tiles[i]!, tiles[j]!)).toBe(false)
})

test('camera altitude and viewport change the requested detail', () => {
  const view = { lon: 127, lat: 37.5, height: 400, pixels: 900, fov: 1 }
  const near = lodTiles(box, view, view), far = lodTiles(box, view, { ...view, height: 30000 })
  expect(near.some(t => t.z === 16)).toBe(true)
  expect(far.every(t => t.z < 16)).toBe(true)
})

test('a horizon-wide coarse root set cannot consume the nearby refinement budget', () => {
  const view = { lon: 127, lat: 37.5, height: 400, pixels: 900, fov: 1 }
  const tiles = lodTiles([125, 35, 129, 39], view, view)
  expect(tiles.some(t => t.z === 16)).toBe(true)
  expect(tiles.some(t => t.z === 13)).toBe(true)
  expect(tiles.length).toBeLessThanOrEqual(320)
})
