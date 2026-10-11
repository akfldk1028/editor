import { expect, test } from 'bun:test'
import { traceSelection } from './rasterSelection'

function raster(broken = false) {
  const width = 80, height = 80, data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const boundary = !broken && (x === 20 || x === 60 || y === 20 || y === 60)
    data.set(boundary ? [140, 140, 120, 255] : [250, 250, 160, 255], (y * width + x) * 4)
  }
  return { width, height, data }
}
const source = [[17, 18], [57, 18], [57, 58], [17, 58], [17, 18]] as const

test('display selection follows enclosed raster boundary without changing the source ring', () => {
  const before = JSON.stringify(source)
  const result = traceSelection(raster(), source)
  expect(result).not.toBeNull()
  expect(Math.min(...result!.map(p => p[0]))).toBe(21)
  expect(Math.max(...result!.map(p => p[0]))).toBe(60)
  expect(JSON.stringify(source)).toBe(before)
})

test('missing boundaries and clipped parcels refuse alignment instead of selecting a whole map', () => {
  expect(traceSelection(raster(true), source)).toBeNull()
  expect(traceSelection(raster(), [[-2, 20], [50, 20], [50, 60], [-2, 60], [-2, 20]])).toBeNull()
})

test('text inside the parcel does not become a hole in the selection', () => {
  const image = raster()
  for (let y = 35; y < 42; y++) for (let x = 30; x < 40; x++) image.data.set([90, 20, 90, 255], (y * 80 + x) * 4)
  const result = traceSelection(image, source)
  expect(result).not.toBeNull()
  expect(result!.length).toBeLessThanOrEqual(9)
})

test('text touching an edge does not bend that display edge around the label', () => {
  const image = raster()
  for (let y = 54; y <= 60; y++) for (let x = 36; x < 43; x++) image.data.set([90, 20, 90, 255], (y * 80 + x) * 4)
  const result = traceSelection(image, source)
  expect(result).not.toBeNull()
  expect(result).toHaveLength(5)
  expect(Math.max(...result!.map(p => p[1]))).toBeCloseTo(60, 0)
})
