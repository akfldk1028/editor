import earcut from 'earcut'
import { footprintBounds, type Footprint } from './building-geometry'
import { footprintRings } from './footprint-rings'

// Part of immutable output identity; never resume pre-normalization meshes.
export const BUILDING_MESH_REVISION = 'footprint-holes-obb-v3'

const rad = Math.PI / 180
export function earth(lon: number, lat: number, height: number): number[] {
  const l = lon * rad, p = lat * rad, n = 6378137 / Math.sqrt(1 - 0.00669437999014 * Math.sin(p) ** 2)
  return [(n + height) * Math.cos(p) * Math.cos(l), (n + height) * Math.cos(p) * Math.sin(l), (n * (1 - 0.00669437999014) + height) * Math.sin(p)]
}

export function frame(lon: number, lat: number) {
  const l = lon * rad, p = lat * rad, origin = earth(lon, lat, 0)
  const east = [-Math.sin(l), Math.cos(l), 0], north = [-Math.sin(p) * Math.cos(l), -Math.sin(p) * Math.sin(l), Math.cos(p)]
  const up = [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)]
  return { transform: [...east, 0, ...north, 0, ...up, 0, ...origin, 1],
    point: (x: number, y: number, z: number) => {
      const v = earth(x, y, z).map((a, i) => a - origin[i]!)
      const dot = (axis: number[]) => axis.reduce((s, a, i) => s + a * v[i]!, 0)
      return [dot(east), dot(up), -dot(north)] // glTF Y-up -> tile ENU Z-up
    } }
}

export function coarseFootprint(f: Footprint): Footprint {
  if (f.ring.length < 3) return f
  const [lon, lat] = f.ring[0]!, scale = Math.cos(lat! * rad)
  const points = f.ring.map(p => [(p[0]! - lon!) * scale, p[1]! - lat!])
    .sort((a, b) => a[0]! - b[0]! || a[1]! - b[1]!)
    .filter((p, i, all) => !i || p[0] !== all[i - 1]![0] || p[1] !== all[i - 1]![1])
  const cross = (a: number[], b: number[], c: number[]) => (b[0]! - a[0]!) * (c[1]! - a[1]!) - (b[1]! - a[1]!) * (c[0]! - a[0]!)
  const half = (vertices: number[][]) => {
    const out: number[][] = []
    for (const p of vertices) {
      while (out.length > 1 && cross(out.at(-2)!, out.at(-1)!, p) <= 0) out.pop()
      out.push(p)
    }
    out.pop(); return out
  }
  const hull = [...half(points), ...half([...points].reverse())]
  if (hull.length < 3) return f
  let bestArea = Infinity, rectangle: number[][] = []
  for (let i = 0; i < hull.length; i++) {
    const a = hull[i]!, b = hull[(i + 1) % hull.length]!, dx = b[0]! - a[0]!, dy = b[1]! - a[1]!
    const length = Math.hypot(dx, dy), ux = dx / length, uy = dy / length
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const p of hull) {
      const x = p[0]! * ux + p[1]! * uy, y = -p[0]! * uy + p[1]! * ux
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y)
    }
    const area = (maxX - minX) * (maxY - minY)
    if (area >= bestArea) continue
    bestArea = area
    rectangle = [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY]]
      .map(([x, y]) => [lon! + (x! * ux - y! * uy) / scale, lat! + x! * uy + y! * ux])
  }
  return { ...f, ring: [...rectangle, rectangle[0]!] }
}

export function meshFootprintBounds(f: Footprint): [number, number, number, number] {
  const a = footprintBounds(f), b = footprintBounds(coarseFootprint(f))
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]
}

const padded = (bytes: Uint8Array, alignment: number, fill = 0) => {
  const out = new Uint8Array(Math.ceil(bytes.length / alignment) * alignment).fill(fill)
  out.set(bytes); return out
}
const jsonBytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))

/** Bake triangle buffers once, with feature IDs retained for parcel hiding and height provenance. */
export function bakeMesh(features: Footprint[], origin: ReturnType<typeof frame>, coarse: boolean): Uint8Array {
  const positions: number[] = [], normals: number[] = [], ids: number[] = []
  const triangle = (a: number[], b: number[], c: number[], id: number) => {
    const u = b.map((v, i) => v - a[i]!), v = c.map((v, i) => v - a[i]!)
    const n = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!]
    const length = Math.hypot(...n)
    if (length < 1e-10) return
    for (const p of [a, b, c]) { positions.push(...p); normals.push(...n.map(x => x / length)); ids.push(id) }
  }
  features.forEach((source, id) => {
    if (!Number.isFinite(source.z)) throw new Error(`Missing measured ground datum: ${source.key}`)
    const f = coarse ? coarseFootprint(source) : source
    const rings = footprintRings(f)
    if (!rings.length) return
    const ring = rings.flat(), holes: number[] = []
    let count = 0
    for (const r of rings) { if (count) holes.push(count); count += r.length }
    const top = ring.map(p => origin.point(p[0]!, p[1]!, f.z! + f.h))
    const bottom = ring.map(p => origin.point(p[0]!, p[1]!, Math.min(0, f.z!) - 12))
    const indices = earcut(ring.flat(), holes, 2)
    for (let i = 0; i < indices.length; i += 3) {
      triangle(top[indices[i]!]!, top[indices[i + 1]!]!, top[indices[i + 2]!]!, id)
      triangle(bottom[indices[i]!]!, bottom[indices[i + 2]!]!, bottom[indices[i + 1]!]!, id)
    }
    let start = 0
    for (const r of rings) {
      for (let k = 0; k < r.length; k++) {
        const i = start + k, j = start + (k + 1) % r.length
        triangle(bottom[i]!, bottom[j]!, top[j]!, id); triangle(bottom[i]!, top[j]!, top[i]!, id)
      }
      start += r.length
    }
  })
  const arrays = [new Float32Array(positions), new Float32Array(normals), new Uint32Array(ids)]
  const views: { buffer: number; byteOffset: number; byteLength: number; target: number }[] = []
  let size = 0
  for (const a of arrays) { views.push({ buffer: 0, byteOffset: size, byteLength: a.byteLength, target: 34962 }); size += a.byteLength }
  const binary = new Uint8Array(size)
  arrays.forEach((a, i) => binary.set(new Uint8Array(a.buffer), views[i]!.byteOffset))
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity]
  positions.forEach((v, i) => { min[i % 3] = Math.min(min[i % 3]!, v); max[i % 3] = Math.max(max[i % 3]!, v) })
  const doc = { asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1, _BATCHID: 2 }, material: 0 }] }],
    materials: [{ doubleSided: true, pbrMetallicRoughness: { baseColorFactor: [0.965, 0.965, 0.946, 1], metallicFactor: 0, roughnessFactor: 1 } }],
    buffers: [{ byteLength: size }], bufferViews: views, accessors: [
      { bufferView: 0, componentType: 5126, count: ids.length, type: 'VEC3', min, max },
      { bufferView: 1, componentType: 5126, count: ids.length, type: 'VEC3' },
      { bufferView: 2, componentType: 5125, count: ids.length, type: 'SCALAR' },
    ] }
  const json = padded(jsonBytes(doc), 4, 32), glb = new Uint8Array(28 + json.length + binary.length), dv = new DataView(glb.buffer)
  dv.setUint32(0, 0x46546c67, true); dv.setUint32(4, 2, true); dv.setUint32(8, glb.length, true)
  dv.setUint32(12, json.length, true); dv.setUint32(16, 0x4e4f534a, true); glb.set(json, 20)
  dv.setUint32(20 + json.length, binary.length, true); dv.setUint32(24 + json.length, 0x004e4942, true); glb.set(binary, 28 + json.length)
  const ftRaw = jsonBytes({ BATCH_LENGTH: features.length })
  const ft = new Uint8Array(Math.ceil((28 + ftRaw.length) / 8) * 8 - 28).fill(32); ft.set(ftRaw)
  const bt = padded(jsonBytes({ lon: features.map(f => f.ring[0]![0]), lat: features.map(f => f.ring[0]![1]),
    status: features.map(f => f.s), key: features.map(f => f.key) }), 8, 32)
  const out = new Uint8Array(28 + ft.length + bt.length + glb.length), header = new DataView(out.buffer)
  header.setUint32(0, 0x6d643362, true); header.setUint32(4, 1, true); header.setUint32(8, out.length, true)
  header.setUint32(12, ft.length, true); header.setUint32(20, bt.length, true)
  out.set(ft, 28); out.set(bt, 28 + ft.length); out.set(glb, 28 + ft.length + bt.length)
  return out
}
