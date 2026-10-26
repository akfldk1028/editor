import { expect, test } from 'bun:test'
import { BuildingTiles } from './building-tiles'

test('asynchronous building upload requests frames until ready, then returns to idle', async () => {
  const updates = new Set<() => void>()
  const event = (listeners = new Set<() => void>()) => ({ addEventListener: (fn: () => void) => {
    listeners.add(fn); return () => listeners.delete(fn)
  } })
  let requested = 0
  const viewer = { scene: { postRender: event(), postUpdate: event(updates), requestRender: () => { requested++ },
    frameState: { creditDisplay: { addStaticCredit() {} } }, primitives: { remove() {} } } }
  const manager = new BuildingTiles(viewer, { Credit: class {} }, () => {},
    Promise.resolve({ archive: { getZxy() {} }, Pbf: null, VectorTile: null })) as any
  await Promise.resolve()
  const primitive = { ready: false, show: true }
  const entry = { tile: { key: '16/0/0', z: 16, x: 0, y: 0 }, features: [], visible: [], heights: [], primitives: [primitive] }
  manager.entries.set(entry.tile.key, entry)
  manager.desired.add(entry.tile.key)
  requested = 0
  for (const update of updates) update()
  expect(requested).toBe(1)
  primitive.ready = true
  requested = 0
  for (const update of updates) update()
  expect(requested).toBe(0)
  manager.dispose()
  expect(updates.size).toBe(0)
})
