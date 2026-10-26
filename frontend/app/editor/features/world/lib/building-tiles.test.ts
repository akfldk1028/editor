import { expect, test } from 'bun:test'
import { BuildingTiles } from './building-tiles'
import { tilesIn } from './building-geometry'

function fixture(archive: any, failure?: Error, firstFrame?: () => void) {
  const event = () => {
    const listeners = new Set<() => void>()
    return { addEventListener: (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn) }, emit: () => { for (const fn of listeners) fn() } }
  }
  const primitives: any[] = []
  const viewer = { terrainProvider: { sampleHeight: async (_lon: number, _lat: number) => 7 }, scene: { postRender: event(), postUpdate: event(), requestRender: () => {},
    frameState: { creditDisplay: { addStaticCredit: () => {} } }, globe: { getHeight: () => 0, tileLoadProgressEvent: event() },
    primitives: { add: (p: any) => { primitives.push(p); return p }, remove: (p: any) => { const i = primitives.indexOf(p); if (i >= 0) primitives.splice(i, 1) } } } }
  class Holder { constructor(options: any) { Object.assign(this, options) } }
  class PolygonGeometry extends Holder { static fromPositions(options: any) { return options } }
  class PolygonHierarchy { constructor(public positions: number[], public holes: PolygonHierarchy[] = []) {} }
  const C = { Credit: Holder, GeometryInstance: Holder, Primitive: Holder,
    PolygonGeometry, PolygonHierarchy, Cartesian3: { fromDegreesArray: (x: any) => x },
    Cartographic: { fromDegrees: (x: number, y: number) => ({ x, y }) },
    GeometryOffsetAttribute: { ALL: 2 }, OffsetGeometryInstanceAttribute: Holder,
    PerInstanceColorAppearance: Object.assign(Holder, { VERTEX_FORMAT: {} }),
    ColorGeometryInstanceAttribute: { fromColor: (x: any) => x }, Color: { fromCssColorString: () => ({ withAlpha: (alpha: number) => alpha }) } }
  const manager = new BuildingTiles(viewer, C, () => {}, failure ? Promise.reject(failure) : Promise.resolve({ archive, Pbf: null, VectorTile: null }), firstFrame) as any
  return { manager, primitives, viewer }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

test('arriving datums finish the current geometry before one coalesced rebuild', async () => {
  const { manager, viewer, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const schedule = manager.scheduleWork.bind(manager)
  manager.scheduleWork = () => {}
  const answers: ((z: number) => void)[] = []
  viewer.terrainProvider.sampleHeight = () => new Promise(resolve => answers.push(resolve))
  const features = buildings(3).map((f, i) => ({ ...f, z: i === 0 ? 93 : undefined }))
  const entry = { tile: { z: 16, x: 0, y: 0, key: 'coalesced' }, features, primitives: [], heights: [] as number[], visible: [] }
  manager.entries.set(entry.tile.key, entry); manager.desired.add(entry.tile.key)
  try {
    manager.build(entry)
    const running = manager.work.get(entry)
    expect(running.next().done).toBe(false)
    answers[0]!(94)
    await new Promise(resolve => setTimeout(resolve, 45))
    expect(manager.work.get(entry)).toBe(running)
    answers[1]!(95)
    await manager.datumJobs.get(entry)
    expect(manager.work.get(entry)).toBe(running)
    manager.scheduleWork = schedule; schedule()
    await finishWork(manager)
    expect(primitives.map((p: any) => p.geometryInstances.length)).toEqual([1, 3])
    expect(entry.heights).toEqual([93, 94, 95])
  } finally { manager.dispose() }
})

test('ground and site changes replace a coalesced datum rebuild immediately', async () => {
  for (const change of ['ground', 'site']) {
    const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
    await flush()
    const schedule = manager.scheduleWork.bind(manager); manager.scheduleWork = () => {}
    const features = buildings(2)
    const entry = { tile: { z: 16, x: 0, y: 0, key: change }, features, primitives: [], heights: [] as number[], visible: [] }
    manager.entries.set(change, entry); manager.desired.add(change)
    try {
      manager.build(entry); const previous = manager.work.get(entry); previous.next()
      manager.buildAfterDatums(entry, features, false)
      expect(manager.datumRebuilds.has(entry)).toBe(true)
      if (change === 'ground') manager.setGround(40, 40)
      else manager.setSite([[126, 37], [128, 37], [128, 38], [126, 38], [126, 37]], true)
      expect(manager.work.get(entry)).not.toBe(previous)
      expect(manager.datumRebuilds.has(entry)).toBe(false)
      manager.scheduleWork = schedule; schedule(); await finishWork(manager)
      expect(entry.heights).toEqual(change === 'ground' ? [40, 40] : [])
    } finally { manager.dispose() }
  }
})

test('eviction and disposal discard deferred datum rebuilds without creating late geometry', async () => {
  for (const action of ['remove', 'dispose']) {
    const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
    await flush()
    manager.scheduleWork = () => {}
    const entry = { tile: { z: 16, x: 0, y: 0, key: action }, features: buildings(2), primitives: [], heights: [], visible: [] }
    manager.entries.set(action, entry); manager.desired.add(action)
    manager.build(entry); manager.work.get(entry).next()
    manager.buildAfterDatums(entry, entry.features, false)
    try {
      if (action === 'remove') manager.remove(entry)
      else manager.dispose()
      expect(manager.work.has(entry)).toBe(false)
      expect(manager.datumRebuilds.has(entry)).toBe(false)
      await flush(); expect(primitives).toHaveLength(0)
    } finally { manager.dispose() }
  }
})

test('runtime roof lookup leaves courtyards open and still finds a separate annex', async () => {
  const { manager }=fixture({getZxy:()=>Promise.resolve(undefined)})
  await flush()
  const courtyard={key:'court',ring:[[0,0],[10,0],[10,10],[0,10],[0,0]],holes:[[[2,2],[8,2],[8,8],[2,8],[2,2]]],z:50,h:20}
  manager.supplement.visible=[courtyard]
  try {
    expect(manager.heightAt(1,1)).toBe(70)
    expect(manager.heightAt(5,5)).toBeUndefined()
    manager.supplement.visible.push({ring:[[4,4],[6,4],[6,6],[4,6],[4,4]],z:50,h:5})
    expect(manager.heightAt(5,5)).toBe(55)
  } finally {manager.dispose()}
})

test('fallback geometry retains courtyard holes when a ground change rebuilds the extrusion', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const hole = [[127.000002, 37.500001], [127.000005, 37.500001], [127.000004, 37.500003], [127.000002, 37.500001]]
  const feature = { ...buildings(1)[0], holes: [hole] }
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'courtyard' }, features: [feature], primitives: [], heights: [], visible: [] }
  manager.entries.set('courtyard', entry); manager.desired.add('courtyard')
  try {
    manager.setGround(35, 35); await finishWork(manager)
    const geometry = primitives.at(-1).geometryInstances[0].geometry
    expect(geometry.polygonHierarchy?.holes[0]?.positions).toEqual(hole.flat())
    expect(geometry.height).toBe(35)
    expect(geometry.extrudedHeight).toBe(45)
  } finally { manager.dispose() }
})

test('live GeoJSON supplement retains courtyard interior rings', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const original = globalThis.fetch, outer = buildings(1)[0]!.ring
  const hole = [[127.000002, 37.500001], [127.000005, 37.500001], [127.000004, 37.500003], [127.000002, 37.500001]]
  globalThis.fetch = (async () => Response.json({ status: 'ok', features: { type: 'FeatureCollection', features: [{
    type: 'Feature', geometry: { type: 'Polygon', coordinates: [outer, hole] }, properties: { id: 'court', height_m: 10, top_m: 60 },
  }] } })) as typeof fetch
  try {
    await manager.supplementNear(127, 37.5)
    expect(manager.supplement.features[0]?.holes).toEqual([hole])
    expect(manager.supplement.features[0]?.z).toBe(50)
  } finally { globalThis.fetch = original; manager.dispose() }
})

test('progress reports reuse unchanged footprint counts and invalidate when visible geometry changes', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  let reads = 0
  const feature = { ...buildings(1)[0], get s() { reads++; return 'm' } }
  const entry = { tile: { z: 16, x: 0, y: 0, key: 'counted' }, features: [], primitives: [], heights: [], visible: [feature] }
  manager.entries.set('counted', entry); manager.desired.add('counted')
  const reports: any[] = []
  manager.changed = (counts: any, pending: number) => reports.push({ counts, pending })
  manager.report(); const firstReads = reads
  manager.running = 3; manager.report()
  expect(reads).toBe(firstReads)
  expect(reports.at(-1)).toEqual({ counts: { measured: 1, estimated: 0, unknown: 0 }, pending: 3 })
  entry.visible = [{ ...feature, s: 'u' }]
  manager.report()
  expect(reports.at(-1).counts).toEqual({ measured: 0, estimated: 0, unknown: 1 })
  manager.desired.clear(); manager.report()
  expect(reports.at(-1).counts).toEqual({ measured: 0, estimated: 0, unknown: 0 })
  manager.dispose()
})

test('unchanged loaded buildings retain their GPU primitive across coverage updates', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(3), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry); manager.desired.add('near')
  manager.build(entry); await finishWork(manager)
  const original = entry.primitives[0]
  original.ready = true
  manager.build(entry); await finishWork(manager)
  expect(entry.primitives[0]).toBe(original)
  expect(manager.retired).toHaveLength(0)
  manager.dispose()
})

test('LOD parent remains visible while its replacement awaits measured ground', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const parent = { tile: { z: 13, x: 0, y: 0, key: '13/0/0' }, features: [], heights: [], visible: [], primitives: [{ ready: true, show: true }] }
  const child = { tile: { z: 16, x: 0, y: 0, key: '16/0/0' }, features: [], heights: [], visible: [], primitives: [], needsBuild: true }
  manager.entries.set(parent.tile.key, parent); manager.entries.set(child.tile.key, child)
  manager.previous.add(parent.tile.key); manager.desired.add(child.tile.key)
  viewer.scene.postRender.emit()
  expect(parent.primitives[0]!.show).toBe(true)
  expect(manager.previous.has(parent.tile.key)).toBe(true)
  manager.dispose()
})

test('source DEM datum stays fixed while displayed terrain loads and changes detail', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const f = { ...buildings(1)[0], z: 93 }
  for (const terrain of [0, 60, 92.5, 93.5, 60]) {
    viewer.scene.globe.getHeight = () => terrain
    const job = manager.ground(f, new Map())
    let result = job.next()
    while (!result.done) result = job.next()
    expect(result.value.z).toBe(93)
    expect(result.value.bottom).toBeLessThanOrEqual(terrain)
  }
  manager.dispose()
})

test('unknown building heights remain labeled unknown but render in one opaque batch', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const features = buildings(2)
  features[1]!.s = 'u'
  const entry = { tile: { z: 16, x: 0, y: 0, key: 'mixed' }, features, primitives: [], heights: [], visible: [] }
  manager.entries.set('mixed', entry)
  manager.desired.add('mixed')
  manager.build(entry)
  await finishWork(manager)
  expect(primitives).toHaveLength(1)
  expect(primitives[0].appearance.translucent).toBe(false)
  expect(primitives[0].geometryInstances.map((i: any) => i.attributes.color)).toEqual([1, 1])
  expect(features[1]!.s).toBe('u')
  manager.dispose()
})

function buildings(count: number) {
  return Array.from({ length: count }, (_, i) => ({ key: `b${i}`, pnu: '', h: 10, s: 'm', z: 0,
    ring: [[127 + i / 10000, 37.5], [127.00001 + i / 10000, 37.5],
      [127.00001 + i / 10000, 37.50001], [127 + i / 10000, 37.5]] }))
}

test('tile preparation yields to input and disposal cancels queued geometry', async () => {
  const { manager, viewer, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  let samples = 0
  viewer.scene.globe.getHeight = () => { samples++; return 0 }
  const entry = { tile: { z: 16, x: 0, y: 0, key: 'dense' }, features: buildings(500), primitives: [], heights: [], visible: [] }
  manager.entries.set('dense', entry)
  manager.desired.add('dense')
  manager.build(entry)
  expect(samples).toBe(0)
  manager.dispose()
  await flush()
  expect(samples).toBe(0)
  expect(primitives).toHaveLength(0)
})

test('initial preview contains nearby buildings without waiting for geometry workers', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const entry = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(40), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.focusDegrees = { lon: 127, lat: 37.5 }
  manager.selectPreview()
  expect(entry.visible.length).toBeGreaterThan(1)
  expect(entry.visible.length).toBeLessThan(40)
  expect(primitives.every(p => p.asynchronous === false)).toBe(true)
  expect(entry.visible[0].key).toBe('b0')
  manager.dispose()
})

test('source datums never ray-test rendered terrain during preparation or terrain progress', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  let samples = 0
  viewer.scene.globe.getHeight = () => { samples++; return 50 }
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(1).map(f => ({ ...f, z: 93 })), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.selectPreview()
  viewer.scene.globe.tileLoadProgressEvent.emit()
  viewer.scene.postUpdate.emit()
  await finishWork(manager)
  expect(samples).toBe(0)
  expect(entry.heights).toEqual([93])
  expect(entry.bottoms).toEqual([-12])
  manager.dispose()
})

async function finishWork(manager: any) {
  for (let i = 0; i < 200 && manager.work.size; i++) await flush()
  expect(manager.work.size).toBe(0)
}

test('geometry uses the latest focus rather than response arrival order across LODs', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const entry = (z: number, x: number, name: string) => ({
    tile: { z, x, y: 0, key: name }, features: buildings(1).map(f => ({ ...f, key: name })),
    primitives: [], heights: [], visible: [],
  })
  const far = entry(16, 100, 'far'), near = entry(13, 25, 'near')
  manager.desired.add('far'); manager.desired.add('near')
  manager.desired.add('far'); manager.desired.add('near')
  manager.focus = [100, 0]
  manager.build(far)
  manager.build(near)
  // A camera move before the next slice changes which ready job goes first.
  manager.focus = [201, 0]
  await finishWork(manager)
  expect(primitives.map(p => p.geometryInstances[0].id)).toEqual(['near/0', 'far/0'])
  manager.dispose()
})

test('missing datums stay hidden until a stable sample resolves, then never follow rendered terrain', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  let resolve!: (z: number) => void
  let calls = 0
  viewer.terrainProvider.sampleHeight = () => { calls++; return new Promise(r => { resolve = r }) }
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(1).map(f => ({ ...f, z: undefined })), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.selectPreview()
  expect(entry.visible).toHaveLength(0)
  expect(entry.primitives).toHaveLength(0)
  await flush()
  expect(calls).toBe(1)
  resolve(93)
  await flush()
  await finishWork(manager)
  expect(entry.heights).toEqual([93])
  viewer.scene.globe.getHeight = () => 200
  viewer.scene.globe.tileLoadProgressEvent.emit()
  viewer.scene.postUpdate.emit()
  await finishWork(manager)
  expect(entry.heights).toEqual([93])
  expect(calls).toBe(1)
  manager.dispose()
})

test('one slow DEM response does not hold back buildings whose measured heights are ready', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const resolves: ((z: number) => void)[] = []
  viewer.terrainProvider.sampleHeight = () => new Promise(resolve => resolves.push(resolve))
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(2).map(f => ({ ...f, z: undefined })), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry); manager.desired.add('near'); manager.selectPreview()
  resolves[0]!(93)
  await new Promise(resolve => setTimeout(resolve, 80))
  await finishWork(manager)
  expect(entry.visible).toHaveLength(1)
  expect(entry.heights).toEqual([93])
  resolves[1]!(94)
  await flush(); await finishWork(manager)
  expect(entry.heights).toEqual([93, 94])
  manager.dispose()
})

test('replacement keeps the old buildings until the new primitives are ready', async () => {
  const { manager, viewer, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const old = { ready: true }
  primitives.push(old)
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(2), primitives: [old], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.desired.add('near')
  manager.build(entry)
  await finishWork(manager)
  viewer.scene.postRender.emit()
  expect(primitives.includes(old)).toBe(true)
  for (const p of entry.primitives) p.ready = true
  viewer.scene.postRender.emit()
  expect(primitives.includes(old)).toBe(false)
  expect(primitives).toHaveLength(1)
  manager.dispose()
})

test('a ground-mode change cancels in-progress terrain geometry', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(2), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.desired.add('near')
  manager.build(entry)
  manager.setGround(35, 35)
  await finishWork(manager)
  expect(entry.heights).toEqual([35, 35])
  expect(entry.bottoms).toEqual([35, 35])
  manager.dispose()
})

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

test('a distant move cancels obsolete tile requests so the new view is not queued behind them', async () => {
  const calls: { signal: AbortSignal; x: number }[] = []
  const { manager } = fixture({ getZxy: (_z: number, x: number, _y: number, signal: AbortSignal) =>
    new Promise((_resolve, reject) => {
      calls.push({ signal, x })
      signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true })
    }) })
  manager.load([127, 37.4, 127.1, 37.6], { lon: 127.05, lat: 37.5 })
  await flush()
  const old = calls.slice()
  expect(old).toHaveLength(8)
  manager.load([129, 35.1, 129.1, 35.3], { lon: 129.05, lat: 35.2 })
  await flush()
  expect(old.every(c => c.signal.aborted)).toBe(true)
  expect(calls.length).toBeGreaterThan(8)
  expect(manager.running).toBeLessThanOrEqual(8)
  expect(manager.tileError).toBe('')
  manager.dispose()
})

test('a new close view requests a coarse parent first and keeps it until detail is ready', async () => {
  const requests: { z: number; x: number; y: number }[] = []
  const { manager } = fixture({ getZxy: (z: number, x: number, y: number) => {
    requests.push({ z, x, y }); return new Promise(() => {})
  } })
  await flush()
  manager.firstRendered = true
  manager.load([129, 35.2, 129.001, 35.201], { lon: 129, lat: 35.2 })
  expect(requests[0]?.z).toBe(13)
  expect(requests.some(t => t.z === 16)).toBe(true)
  const p = requests[0]!
  expect(manager.previous.has(`${p.z}/${p.x}/${p.y}`)).toBe(true)
  manager.dispose()
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

test('zoom-out queues overview coverage for every exposed region before central detail', async () => {
  const requests: any[] = []
  const { manager } = fixture({ getZxy: (z: number, x: number, y: number) => {
    requests.push({ z, x, y, key: `${z}/${x}/${y}` }); return new Promise(() => {})
  } })
  await flush()
  manager.firstRendered = true
  const focus = { lon: 127, lat: 37.5 }
  manager.load([126.96, 37.46, 127.08, 37.58], focus, { ...focus, height: 700, pixels: 900, fov: 1 })
  const scheduled = [...requests, ...manager.queue]
  const roots = scheduled.filter(t => t.z === 13)
  expect(roots.length).toBeGreaterThan(1)
  expect(new Set(scheduled.map(t => t.key)).size).toBe(scheduled.length)
  const firstDetail = scheduled.findIndex(t => t.z > 13)
  expect(firstDetail).toBe(roots.length)
  for (const t of scheduled.filter(t => t.z > 13)) {
    const scale = 2 ** (t.z - 13)
    expect(roots.some(p => p.x === Math.floor(t.x / scale) && p.y === Math.floor(t.y / scale))).toBe(true)
  }
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
  manager.entries.set('far', { tile: { z: 16, x: 0, y: 0, key: 'far' }, primitives: [p], features: [], visible: [], heights: [] })
  manager.load([127, 37.5, 127.001, 37.501], { lon: 127, lat: 37.5 })
  expect(p.show).toBe(false)
  manager.dispose()
})

test('moving before the preview is ready selects a loaded tile in the new view', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const box: [number, number, number, number] = [127, 37.5, 127.001, 37.501]
  const tile = tilesIn(box, { lon: 127, lat: 37.5 })[0]!
  const entry = { tile, primitives: [], features: [{ key: 'new', pnu: '', h: 10, s: 'm', z: 0,
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
  for (let i = 0; i < 110; i++) {
    const p = {}
    primitives.push(p)
    manager.entries.set(String(i), { tile: { z: 16, x: i, y: 0, key: String(i) }, primitives: [p], features: [], visible: [], heights: [] })
  }
  manager.focus = [109, 0]
  manager.evict()
  expect(manager.entries.size).toBe(96)
  expect(manager.entries.has('0')).toBe(false)
  expect(manager.entries.has('109')).toBe(true)
  expect(primitives.length).toBe(96)
  manager.dispose()
  expect(primitives.length).toBe(0)
})

test('a broad zoom-out keeps a separate cache of recently drawn detail for zooming back in', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const cached = { tile: { z: 16, x: 100, y: 100, key: 'detail' }, features: [], visible: [], heights: [], primitives: [{ ready: true, show: false }] }
  manager.entries.set('detail', cached)
  primitives.push(...cached.primitives)
  for (let i = 0; i < 120; i++) {
    const key = `overview-${i}`
    manager.desired.add(key)
    manager.entries.set(key, { tile: { z: 13, x: i, y: 0, key }, features: [], visible: [], heights: [], primitives: [] })
  }
  manager.evict()
  expect(manager.entries.get('detail')).toBe(cached)
  expect(primitives).toContain(cached.primitives[0])
  manager.dispose()
})

test('wide-view requests use the selected archive zoom', async () => {
  const zooms: number[] = []
  const { manager } = fixture({ getZxy: (z: number) => { zooms.push(z); return Promise.resolve(undefined) } })
  manager.load([126.95, 37.45, 127.15, 37.65], { lon: 127.05, lat: 37.55 })
  await flush()
  expect(zooms.length).toBeGreaterThan(0)
  expect(zooms.every(z => z >= 13 && z < 16)).toBe(true)
  manager.dispose()
})

test('changing detail level keeps old geometry until all replacement tiles are ready', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const focus = { lon: 127, lat: 37.5 }
  const near = tilesIn([127, 37.5, 127.001, 37.501], focus)[0]!
  const old = { ready: true, show: true }
  manager.entries.set(near.key, { tile: near, features: [], primitives: [old], visible: [], heights: [] })
  manager.desired.add(near.key)
  manager.load([126.95, 37.45, 127.15, 37.65], focus)
  expect(old.show).toBe(true)
  await flush()
  await finishWork(manager)
  const target = manager.entries.get([...manager.desired][0])
  const replacement = { ready: false, show: false }
  target.primitives = [replacement]
  viewer.scene.postRender.emit()
  expect(old.show).toBe(true)
  expect(replacement.show).toBe(false)
  replacement.ready = true
  viewer.scene.postRender.emit()
  expect(old.show).toBe(false)
  expect(replacement.show).toBe(true)
  manager.dispose()
})

test('a missing replacement in another region cannot block a ready region', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const entry = (z: number, x: number, y: number, show: boolean) => ({ tile: { z, x, y, key: `${z}/${x}/${y}` },
    features: [], visible: [], heights: [], primitives: [{ ready: true, show }] })
  const oldNear = entry(16, 400, 400, true), oldFar = entry(16, 440, 400, true), next = entry(14, 100, 100, false)
  for (const e of [oldNear, oldFar, next]) manager.entries.set(e.tile.key, e)
  manager.previous = new Set([oldNear.tile.key, oldFar.tile.key])
  manager.desired = new Set([next.tile.key, '14/110/100'])
  viewer.scene.postRender.emit()
  expect(oldNear.primitives[0].show).toBe(false)
  expect(next.primitives[0].show).toBe(true)
  expect(oldFar.primitives[0].show).toBe(true)
  manager.dispose()
})

test('zooming while a full tile builds retains its already drawn preview', async () => {
  const { manager, primitives } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const focus = { lon: 127, lat: 37.5 }
  const tile = tilesIn([127, 37.5, 127.001, 37.501], focus)[0]!
  const preview = { ready: true, show: true }
  primitives.push(preview)
  const entry: any = { tile, features: buildings(1), primitives: [preview], visible: [], heights: [] }
  manager.entries.set(tile.key, entry)
  manager.desired.add(tile.key)
  manager.build(entry)
  await finishWork(manager)
  expect(entry.primitives[0].ready).not.toBe(true)
  manager.load([126.95, 37.45, 127.15, 37.65], focus)
  expect(preview.show).toBe(true)
  manager.dispose()
})

test('unchanged supplement selection reuses geometry but ground changes rebuild it', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.supplement.features = buildings(3)
  manager.reconcileSupplement()
  await finishWork(manager)
  const original = manager.supplement.primitives[0]
  manager.reconcileSupplement()
  await finishWork(manager)
  expect(manager.supplement.primitives[0]).toBe(original)
  manager.setGround(35, 35)
  await finishWork(manager)
  expect(manager.supplement.primitives[0]).not.toBe(original)
  expect(manager.supplement.heights).toEqual([35, 35, 35])
  manager.dispose()
})

test('switching hidden cached tiles reconciles duplicate live buildings without a network request', async () => {
  let requests = 0
  const { manager } = fixture({ getZxy: () => { requests++; return Promise.resolve(undefined) } })
  await flush()
  manager.firstRendered = true
  const features = buildings(1)
  manager.supplement.features = features
  manager.reconcileSupplement()
  await finishWork(manager)
  expect(manager.supplement.visible).toHaveLength(1)
  manager.setShow(false)
  const box: [number, number, number, number] = [127, 37.5, 127.001, 37.501]
  const focus = { lon: 127, lat: 37.5 }
  for (const tile of tilesIn(box, focus)) manager.entries.set(tile.key, { tile, features, visible: features,
    primitives: [{ ready: true, show: false }], heights: [0] })
  manager.load(box, focus)
  manager.setShow(true)
  await finishWork(manager)
  expect(requests).toBe(0)
  expect(manager.supplement.visible).toHaveLength(0)
  manager.dispose()
})

test('a canceled offscreen rebuild resumes when its cached tile returns', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  manager.setGround(0, 0)
  await finishWork(manager)
  const box: [number, number, number, number] = [127, 37.5, 127.001, 37.501]
  const focus = { lon: 127, lat: 37.5 }, tile = tilesIn(box, focus)[0]!
  const entry: any = { tile, features: buildings(1), primitives: [], visible: [], heights: [] }
  manager.entries.set(tile.key, entry)
  manager.desired.add(tile.key)
  manager.build(entry)
  await finishWork(manager)
  manager.setGround(35, 35)
  manager.load([128, 38, 128.001, 38.001], { lon: 128, lat: 38 })
  expect(manager.work.has(entry)).toBe(false)
  manager.load(box, focus)
  await finishWork(manager)
  expect(entry.heights).toEqual([35])
  manager.dispose()
})

test('a failed live request can be retried at the same location', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const original = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => {
    if (++calls === 1) throw new Error('network timeout')
    return Response.json({ status: 'ok', features: { type: 'FeatureCollection', features: [] } })
  }) as typeof fetch
  try {
    await manager.supplementNear(127, 37.5)
    expect(manager.supplementError).toContain('network timeout')
    await manager.supplementNear(127, 37.5)
    expect(calls).toBe(2)
    expect(manager.supplementError).toBe('')
  } finally { globalThis.fetch = original; manager.dispose() }
})


test('failed missing datums report a settled state and retry only after cooldown', async () => {
  let started = 0
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) }, undefined, () => started++)
  await flush()
  let calls = 0
  viewer.terrainProvider.sampleHeight = async () => { calls++; throw new Error('DEM offline') }
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features: buildings(1).map(f => ({ ...f, z: undefined })), primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.selectPreview()
  await flush()
  expect(entry.visible).toHaveLength(0)
  expect(manager.datumJobs.size).toBe(0)
  expect(manager.datumErrors.get(entry)).toContain('DEM offline')
  expect(started).toBe(1)
  manager.build(entry)
  await flush()
  expect(calls).toBe(1)
  manager.datumRetryAt.set(entry, 0)
  viewer.terrainProvider.sampleHeight = async () => { calls++; return 93 }
  manager.build(entry)
  await flush()
  await finishWork(manager)
  expect(calls).toBe(2)
  expect(entry.heights).toEqual([93])
  expect(manager.datumErrors.has(entry)).toBe(false)
  manager.dispose()
})

test('roof height lookup uses fixed datums and ignores unloaded or hidden footprints', async () => {
  const { manager } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const features = buildings(1).map(f => ({ ...f, z: 93 }))
  const entry: any = { tile: { z: 16, x: 0, y: 0, key: 'near' }, features, primitives: [], heights: [], visible: [] }
  manager.entries.set('near', entry)
  manager.desired.add('near')
  manager.selectPreview()
  expect(manager.heightAt(127.000007, 37.500003)).toBe(103)
  expect(manager.heightAt(128, 38)).toBeUndefined()
  manager.setShow(false)
  expect(manager.heightAt(127.000007, 37.500003)).toBeUndefined()
  manager.dispose()
})


test('failed baked coverage is released only after vector fallback is actually drawable', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  manager.firstRendered = true
  const entry: any = { tile: { z: 16, x: 1, y: 1, key: '16/1/1' }, features: [], heights: [], visible: [],
    primitives: [{ ready: false, show: true }], needsBuild: false }
  manager.entries.set(entry.tile.key, entry); manager.desired.add(entry.tile.key)
  let drawable: any[] = []
  manager.baked = { needsFallback: true, retireFailed: (_wanted: any[], ready: any[]) => { drawable = ready }, dispose() {} }
  try {
    viewer.scene.postRender.emit()
    expect(drawable).toEqual([])
    entry.primitives[0].ready = true; entry.primitives[0].show = false
    viewer.scene.postRender.emit()
    expect(drawable).toEqual([])
    entry.primitives[0].show = true; entry.needsBuild = true
    viewer.scene.postRender.emit()
    expect(drawable).toEqual([])
    entry.needsBuild = false
    viewer.scene.postRender.emit()
    expect(drawable).toEqual([entry.tile])
  } finally { manager.dispose() }
})

test('wide views admit only eight building ground samples across all tiles', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  let calls = 0
  viewer.terrainProvider.sampleHeight = () => { calls++; return new Promise(() => {}) }
  try {
    for (let i = 0; i < 256; i++) {
      const entry = { tile: { z: 13, x: i, y: 0, key: `wide-${i}` }, features: buildings(160).map(f => ({ ...f, z: undefined })),
        primitives: [], heights: [], visible: [] }
      manager.entries.set(entry.tile.key, entry); manager.desired.add(entry.tile.key)
      manager.resolveDatums(entry, entry.features)
    }
    expect(calls).toBe(8)
    expect(manager.datumJobs.size).toBe(256)
  } finally { manager.dispose() }
})

test('ground admission skips obsolete tiles and prioritizes the current focus', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const pending: { lon: number; resolve: (z: number) => void }[] = []
  viewer.terrainProvider.sampleHeight = (lon: number) => new Promise(resolve => pending.push({ lon, resolve }))
  const add = (key: string, lon: number) => {
    const entry = { tile: { z: 16, x: 0, y: 0, key }, features: buildings(32).map(f => ({ ...f, z: undefined,
      ring: f.ring.map(([x, y]) => [x! - 127 + lon, y!]) })), primitives: [], heights: [], visible: [] }
    manager.entries.set(key, entry); manager.desired.add(key); manager.resolveDatums(entry, entry.features)
    return entry
  }
  try {
    const old = add('old', 127)
    expect(pending).toHaveLength(8)
    manager.desired.clear()
    const far = add('far', 129), near = add('near', 128)
    manager.focusDegrees = { lon: 128, lat: 37.5 }
    pending.slice().forEach(p => p.resolve(93))
    await flush()
    expect(pending).toHaveLength(16)
    expect(pending.slice(8).every(p => p.lon >= 128 && p.lon < 128.01)).toBe(true)
    expect(manager.datumJobs.has(old)).toBe(false)
    manager.dispose()
    pending.slice(8).forEach(p => p.resolve(94))
    await flush()
    expect(pending).toHaveLength(16)
    expect(manager.datums.has(far.features[0])).toBe(false)
    expect(manager.datums.has(near.features[0])).toBe(false)
  } finally { manager.dispose() }
})

test('bounded ground admission drains cached samples while yielding to input', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  let calls = 0, callsAtInput = 0
  viewer.terrainProvider.sampleHeight = async () => { calls++; return 93 }
  const entry = { tile: { z: 13, x: 0, y: 0, key: 'cached' }, features: buildings(256).map(f => ({ ...f, z: undefined })),
    primitives: [], heights: [], visible: [] }
  manager.entries.set(entry.tile.key, entry); manager.desired.add(entry.tile.key)
  const input = new Promise<void>(resolve => setTimeout(() => { callsAtInput = calls; resolve() }, 0))
  try {
    manager.resolveDatums(entry, entry.features)
    await input
    expect(callsAtInput).toBeLessThan(256)
    await manager.datumJobs.get(entry)
    expect(calls).toBe(256)
    expect(entry.features.every(f => manager.datums.get(f) === 93)).toBe(true)
    expect(manager.datumJobs.size).toBe(0)
    expect(manager.datumBatches.size).toBe(0)
  } finally { manager.dispose() }
})

test('retiring terrain consumers releases admission for cached buildings at the new focus', async () => {
  const { manager, viewer } = fixture({ getZxy: () => Promise.resolve(undefined) })
  await flush()
  const oldRequests: { needed: () => boolean; reject: (reason: Error) => void }[] = []
  ;(viewer.terrainProvider as any).sampleHeight = (lon: number, _lat: number, needed: () => boolean) => lon < 128
    ? new Promise((_resolve, reject) => oldRequests.push({ needed, reject })) : Promise.resolve(93)
  ;(viewer.terrainProvider as any).pruneRequests = () => {
    for (const request of oldRequests) if (!request.needed()) request.reject(new Error('terrain sample retired'))
  }
  const add = (key: string, lon: number) => {
    const entry = { tile: { z: 16, x: 0, y: 0, key }, features: buildings(16).map(f => ({ ...f, z: undefined,
      ring: f.ring.map(([x, y]) => [x! - 127 + lon, y!]) })), primitives: [], heights: [], visible: [] }
    manager.entries.set(key, entry); manager.desired.add(key); manager.resolveDatums(entry, entry.features)
    return entry
  }
  try {
    const old = add('old-pending', 127)
    expect(oldRequests).toHaveLength(8)
    manager.desired.clear()
    const current = add('new-cached', 128)
    const completed = manager.datumJobs.get(current)
    viewer.scene.postUpdate.emit()
    await completed
    expect(current.features.every(f => manager.datums.get(f) === 93)).toBe(true)
    expect(manager.datumJobs.has(old)).toBe(false)
    expect(oldRequests).toHaveLength(8)
    expect(manager.datumRunning).toBe(0)
  } finally { manager.dispose() }
})
