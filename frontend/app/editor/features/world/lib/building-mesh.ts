import type { Footprint } from './building-geometry'
import earcut from 'earcut'
import { earth } from './prebuilt-mesh'
import { footprintRings } from './footprint-rings'

export type BuildingMesh = { positions: Float64Array; normals: Float32Array; bottom: number; top: number }

export function prepareBuildingMesh(feature: Footprint): BuildingMesh | undefined {
  if (!Number.isFinite(feature.z)) return undefined
  const rings = footprintRings(feature)
  if (!rings.length) return undefined
  const ring = rings.flat(), holes: number[] = []
  let count = 0
  for (const r of rings) { if (count) holes.push(count); count += r.length }
  const top = feature.z! + feature.h, bottom = Math.min(0, feature.z!) - 12
  const roof = ring.map(p => earth(p[0]!, p[1]!, top))
  const foot = ring.map(p => earth(p[0]!, p[1]!, bottom))
  const indices = earcut(ring.flat(), holes, 2)
  const positions = new Float64Array((indices.length * 2 + ring.length * 6) * 3)
  const normals = new Float32Array(positions.length)
  let offset = 0
  const triangle = (a: number[], b: number[], c: number[]) => {
    const ux = b[0]! - a[0]!, uy = b[1]! - a[1]!, uz = b[2]! - a[2]!
    const vx = c[0]! - a[0]!, vy = c[1]! - a[1]!, vz = c[2]! - a[2]!
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
    const length = Math.hypot(nx, ny, nz)
    if (length < 1e-12) return
    for (const p of [a, b, c]) {
      positions.set(p, offset); normals.set([nx / length, ny / length, nz / length], offset); offset += 3
    }
  }
  for (let i = 0; i < indices.length; i += 3) {
    const a = indices[i]!, b = indices[i + 1]!, c = indices[i + 2]!
    triangle(roof[a]!, roof[b]!, roof[c]!); triangle(foot[a]!, foot[c]!, foot[b]!)
  }
  let start = 0
  for (const r of rings) {
    for (let k = 0; k < r.length; k++) {
      const i = start + k, j = start + (k + 1) % r.length
      triangle(foot[i]!, foot[j]!, roof[j]!); triangle(foot[i]!, roof[j]!, roof[i]!)
    }
    start += r.length
  }
  return { positions: positions.subarray(0, offset), normals: normals.subarray(0, offset), top, bottom }
}

export async function prepareBuildingMeshes(features: Footprint[], signal: AbortSignal): Promise<ArrayBuffer[]> {
  const transfers: ArrayBuffer[] = []
  let deadline = performance.now() + 4
  for (const feature of features) {
    signal.throwIfAborted()
    feature.mesh = prepareBuildingMesh(feature)
    if (feature.mesh) transfers.push(feature.mesh.positions.buffer as ArrayBuffer, feature.mesh.normals.buffer as ArrayBuffer)
    if (performance.now() >= deadline) {
      await new Promise(resolve => setTimeout(resolve, 0))
      deadline = performance.now() + 4
    }
  }
  signal.throwIfAborted()
  return transfers
}

// Cesium's combine worker can transfer its input; retain the cached source buffers for revisits.
export function preparedGeometry(C: any, mesh: BuildingMesh) {
  const positions = mesh.positions.slice()
  return new C.Geometry({
    attributes: {
      position: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: positions }),
      normal: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.FLOAT, componentsPerAttribute: 3, values: mesh.normals.slice() }),
      applyOffset: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.UNSIGNED_BYTE, componentsPerAttribute: 1,
        values: new Uint8Array(positions.length / 3).fill(1) }),
    },
    // PolygonGeometry fallbacks are indexed; Cesium cannot combine mixed index layouts.
    indices: Uint32Array.from({ length: positions.length / 3 }, (_, i) => i),
    primitiveType: C.PrimitiveType.TRIANGLES,
    boundingSphere: C.BoundingSphere.fromVertices(positions),
    offsetAttribute: C.GeometryOffsetAttribute.ALL,
  })
}
