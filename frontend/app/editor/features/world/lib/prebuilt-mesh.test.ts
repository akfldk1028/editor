import { expect, test } from 'bun:test'
import { bakeMesh, coarseFootprint, earth, frame } from './prebuilt-mesh'
import type { Footprint } from './building-geometry'

const f: Footprint = { key: 'one', pnu: '', s: 'm', z: 93, h: 12,
  ring: [[127, 37], [127.001, 37], [127.001, 37.001], [127, 37.001], [127, 37]] }
test('baked tiles retain feature identity, valid aligned GLB and measured elevations', () => {
  const data = bakeMesh([f], frame(127, 37), false), h = new DataView(data.buffer)
  expect(h.getUint32(0, true)).toBe(0x6d643362)
  expect(h.getUint32(8, true)).toBe(data.length)
  const offset = 28 + h.getUint32(12, true) + h.getUint32(20, true)
  expect(offset % 8).toBe(0)
  expect(h.getUint32(offset, true)).toBe(0x46546c67)
  const jsonSize = h.getUint32(offset + 12, true)
  const doc = JSON.parse(new TextDecoder().decode(data.slice(offset + 20, offset + 20 + jsonSize)))
  expect(doc.accessors[0].max[1]).toBeCloseTo(105, 0)
  expect(doc.accessors[0].min[1]).toBeLessThan(-11)
  expect(doc.accessors[0].count).toBe(36)
  expect(doc.accessors[2].count).toBe(36)
  expect(() => bakeMesh([{ ...f, z: undefined }], frame(127, 37), false)).toThrow('datum')
})
test('ECEF transform uses local metric coordinates and coarse representation retains every building', () => {
  const origin = frame(127, 37)
  expect(origin.point(127, 37, 0).every(x => Math.abs(x) < 1e-6)).toBe(true)
  expect(origin.transform.slice(12, 15)).toEqual(earth(127, 37, 0))
  expect(coarseFootprint(f).h).toBe(f.h)
  expect(coarseFootprint(f).z).toBe(f.z)
})

test('detailed walls face outward for either source ring winding, matching coarse geometry', () => {
  for (const ring of [f.ring, [...f.ring].reverse()]) for (const coarse of [false, true]) {
    const data = bakeMesh([{ ...f, ring }], frame(127, 37), coarse), h = new DataView(data.buffer)
    const offset = 28 + h.getUint32(12, true) + h.getUint32(20, true)
    const jsonSize = h.getUint32(offset + 12, true)
    const doc = JSON.parse(new TextDecoder().decode(data.slice(offset + 20, offset + 20 + jsonSize)))
    const binary = offset + 28 + jsonSize
    const positions = binary + doc.bufferViews[0].byteOffset, normals = binary + doc.bufferViews[1].byteOffset
    const center = frame(127, 37).point(127.0005, 37.0005, 0)
    // Roof/bottom occupy the first 12 vertices; each wall has six vertices.
    for (let vertex = 12; vertex < 36; vertex += 6) {
      const a = Array.from({ length: 3 }, (_, axis) => h.getFloat32(positions + vertex * 12 + axis * 4, true))
      const b = Array.from({ length: 3 }, (_, axis) => h.getFloat32(positions + (vertex + 1) * 12 + axis * 4, true))
      const normal = Array.from({ length: 3 }, (_, axis) => h.getFloat32(normals + vertex * 12 + axis * 4, true))
      expect(normal[0]! * ((a[0]! + b[0]!) / 2 - center[0]!)
        + normal[2]! * ((a[2]! + b[2]!) / 2 - center[2]!)).toBeGreaterThan(0)
    }
  }
})
