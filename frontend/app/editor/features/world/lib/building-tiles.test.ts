import { expect, test } from 'bun:test'
import { BuildingTiles } from './building-tiles'
import { tilesIn } from './building-geometry'

function fixture(archive: any, failure?: Error, firstFrame?: () => void) {
  const event = () => {
    const listeners = new Set<() => void>()
    return { addEventListener: (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn) }, emit: () => { for (const fn of listeners) fn() } }
  }
  const primitives: any[] = []
  const viewer = { scene: { postRender: event(), postUpdate: event(), requestRender: () => {},
    frameState: { creditDisplay: { addStaticCredit: () => {} } }, globe: { getHeight: () => 0 },
    primitives: { add: (p: any) => { primitives.push(p); return p }, remove: (p: any) => { const i = primitives.indexOf(p); if (i >= 0) primitives.splice(i, 1) } } } }
  class Holder { constructor(options: any) { Object.assign(this, options) } }
  const C = { Credit: Holder, GeometryInstance: Holder, Primitive: Holder,
    PolygonGeometry: { fromPositions: (x: any) => x }, Cartesian3: { fromDegreesArray: (x: any) => x },
    Cartographic: { fromDegrees: (x: number, y: number) => ({ x, y }) },
    GeometryOffsetAttribute: { ALL: 2 }, OffsetGeometryInstanceAttribute: Holder,
    PerInstanceColorAppearance: Object.assign(Holder, { VERTEX_FORMAT: {} }),
    ColorGeometryInstanceAttribute: { fromColor: (x: any) => x }, Color: { fromCssColorString: () => ({ withAlpha: (alpha: number) => alpha }) } }
  const manager = new BuildingTiles(viewer, C, () => {}, failure ? Promise.reject(failure) : Promise.resolve({ archive, Pbf: null, VectorTile: null }), firstFrame) as any
  return { manager, primitives, viewer }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

test('eight requests at most; a disposed loader cannot draw a late response', async () => {
  const pending: ((r: any) => void)[] = []
  const { manager, primitives } = fixture({ getZxy: () => new Promise(resolve => pending.push(resolve)) })
  manager.load([127, 37.4, 127.1, 37.6], { lon: 127.05, lat: 37.5 })
  await flush()
  expect(pending.length).toBe(8)
  manager.dispose()
  pending.forEach(resolve => resolve(undefined))
  await flush()
  expect(primitives.length).toBe(0)
  expect(manager.entries.size).toBe(0)
})

test('failed tile is retried on the next move', async () => {
  let calls = 0
  const { manager } = fixture({ getZxy: () => { calls++; return Promise.reject(new Error('offline')) } })
  const box: [number, number, number, number] = [127, 37.5, 127.001, 37.501]
  manager.load(box, { lon: 127, lat: 37.5 })
  await flush()
  const first = calls
  expect(first).toBeGreaterThan(0)
  expect(manager.entries.size).toBe(0)
  expect(manager.backgroundReady).toBe(true)
  manager.load(box, { lon: 127, lat: 37.5 })
  await flush()
  expect(calls).toBe(first * 2)
  manager.dispose()
})

test('manifest failure does not prevent terrain and live context from starting', async () => {
  let started = 0
  const { manager } = fixture(null, new Error('manifest offline'), () => started++)
  await flush()
  expect(started).toBe(1)
  expect(manager.backgroundReady).toBe(true)
  manager.dispose()
})

test('cached tiles outside the current view are hidden', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const p = { show: true }
  primitives.push(p)
  manager.entries.set('far', { tile: { x: 0, y: 0, key: 'far' }, primitives: [p], features: [], visible: [], heights: [] })
  manager.load([127, 37.5, 127.001, 37.501], { lon: 127, lat: 37.5 })
  expect(p.show).toBe(false)
  manager.dispose()
})

test('moving before the preview is ready selects a loaded tile in the new view', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const box: [number, number, number, number] = [127, 37.5, 127.001, 37.501]
  const tile = tilesIn(box, { lon: 127, lat: 37.5 })[0]!
  const entry = { tile, primitives: [], features: [{ key: 'new', pnu: '', h: 10, s: 'm',
    ring: [[127, 37.5], [127.001, 37.5], [127.001, 37.501], [127, 37.5]] }], visible: [], heights: [] }
  manager.entries.set(tile.key, entry)
  manager.preview = { tile: { key: 'old' }, primitives: [], features: [], visible: [], heights: [] }
  manager.load(box, { lon: 127, lat: 37.5 })
  expect(manager.preview).toBe(entry)
  expect(entry.primitives.length).toBe(1)
  manager.dispose()
})

test('panning evicts distant tiles and releases their primitives', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  for (let i = 0; i < 70; i++) {
    const p = {}
    primitives.push(p)
    manager.entries.set(String(i), { tile: { x: i, y: 0, key: String(i) }, primitives: [p], features: [], visible: [], heights: [] })
  }
  manager.focus = [69, 0]
  manager.evict()
  expect(manager.entries.size).toBe(58)
  expect(manager.entries.has('0')).toBe(false)
  expect(manager.entries.has('69')).toBe(true)
  expect(primitives.length).toBe(58)
  manager.dispose()
  expect(primitives.length).toBe(0)
})
