import { expect, test } from 'bun:test'
import { prepareBuildingMesh, prepareBuildingMeshes, preparedGeometry } from './building-mesh'
import type { Footprint } from './building-geometry'

const footprint: Footprint = { key: 'test', pnu: '', h: 10, z: 93, s: 'm',
  ring: [[0, 0], [0.0001, 0], [0.0001, 0.0001], [0, 0.0001], [0, 0]] }

test('prepared extrusion preserves measured roof and buried footing with outward normals', () => {
  for (const ring of [footprint.ring, [...footprint.ring].reverse()]) {
    const mesh = prepareBuildingMesh({ ...footprint, ring })!
    expect(mesh).toBeDefined()
    expect(mesh.positions).toHaveLength(108)
    expect(mesh.normals).toHaveLength(108)
    expect(Math.max(...mesh.positions.filter((_, i) => i % 3 === 0))).toBeCloseTo(6378240, 3)
    expect(Math.min(...mesh.positions.filter((_, i) => i % 3 === 0))).toBeCloseTo(6378125, 3)
    // At the equator the first roof normal points along ECEF +X.
    expect(mesh.normals[0]).toBeCloseTo(1, 5)
    for (let i = 0; i < mesh.normals.length; i += 3) {
      expect(Math.hypot(...mesh.normals.slice(i, i + 3))).toBeCloseTo(1, 5)
    }
  }
})

test('missing ground evidence is not converted to a zero-height datum', () => {
  expect(prepareBuildingMesh({ ...footprint, z: undefined })).toBeUndefined()
  expect(prepareBuildingMesh({ ...footprint, z: NaN })).toBeUndefined()
})

test('triangle buffers transfer without changing height provenance', () => {
  const source = { ...footprint, s: 'u' as const, mesh: prepareBuildingMesh(footprint)! }
  const copy = structuredClone(source, { transfer: [source.mesh.positions.buffer, source.mesh.normals.buffer] })
  expect(source.mesh.positions.byteLength).toBe(0)
  expect(copy.mesh.positions.length).toBe(108)
  expect(copy.s).toBe('u')
  expect(copy.z).toBe(93)
})

test('aborted mesh preparation does not process stale camera work', async () => {
  const controller = new AbortController()
  controller.abort()
  const features: Footprint[] = [{ ...footprint }]
  await expect(prepareBuildingMeshes(features, controller.signal)).rejects.toThrow()
  expect(features[0]!.mesh).toBeUndefined()
})


test('prepared geometry is indexed like polygon fallbacks without changing triangle topology', () => {
  class Value { constructor(options: object) { Object.assign(this, options) } }
  const C = { Geometry: Value, GeometryAttribute: Value,
    ComponentDatatype: { DOUBLE: 1, FLOAT: 2, UNSIGNED_BYTE: 3 },
    PrimitiveType: { TRIANGLES: 4 }, GeometryOffsetAttribute: { ALL: 1 },
    BoundingSphere: { fromVertices: () => ({}) } }
  const mesh = prepareBuildingMesh(footprint)!
  const geometry = preparedGeometry(C, mesh)
  expect(geometry.indices).toBeInstanceOf(Uint32Array)
  const vertices = geometry.attributes.position.values
  const expanded = Array.from(geometry.indices as Uint32Array).flatMap(i => Array.from(vertices.slice(i * 3, i * 3 + 3)))
  expect(expanded).toEqual(Array.from(mesh.positions))
  expect(vertices.buffer).not.toBe(mesh.positions.buffer)
  expect(geometry.indices.length % 3).toBe(0)
})
