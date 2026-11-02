import { expect, test } from 'bun:test'
import { NationalBuildings } from './national-buildings'
import type { NationalBuildingSource } from './national-building-source'

function event() {
  const listeners = new Set<(...args: any[]) => void>()
  return { addEventListener(fn: (...args: any[]) => void) { listeners.add(fn); return () => { listeners.delete(fn) } },
    fire(...args: any[]) { for (const fn of listeners) fn(...args) }, listeners }
}
function setup(deferred = false) {
  const preRender = event(), postRender = event(), tileVisible = event(), tileFailed = event()
  const opened: string[] = [], active = new Set<any>()
  let destroyed = false, resolve!: (v: any) => void
  const tileset = { tileVisible, tileFailed, tilesLoaded: true, destroy() { destroyed = true } }
  const viewer = { scene: { preRender, postRender, requestRender() {}, primitives: {
    add(v: any) { active.add(v) }, remove(v: any) { active.delete(v); v.destroy() },
  } } }
  const C = { Cesium3DTileset: { fromUrl(url: string) { opened.push(url); return deferred ? new Promise(r => { resolve = r }) : Promise.resolve(tileset) } },
    Cesium3DTileColorBlendMode: { REPLACE: 2 }, Color: { fromCssColorString(color: string) { return { withAlpha: (alpha: number) => ({ color, alpha }) } } } }
  const reports: any[] = []
  const renderer = new NationalBuildings(viewer, C, { url: 'national/test/tileset.json' } as NationalBuildingSource, (...args) => reports.push(args))
  return { renderer, opened, active, tileset, preRender, postRender, tileVisible, reports, resolve: () => resolve(tileset), destroyed: () => destroyed }
}

test('one hierarchical tileset covers all camera views with opaque neutral feature styling', async () => {
  const s = setup(); await Promise.resolve()
  for (let i = 0; i < 40; i++) s.renderer.load([i, 0, i + 1, 1], { lon: i, lat: 0 })
  expect(s.opened).toHaveLength(1); expect(s.active.size).toBe(1)
  const feature = { show: true, color: undefined as unknown, getProperty: (key: string) => ({ lon: 1, lat: 1, status: 'u' })[key as 'lon'] }
  s.preRender.fire(); s.tileVisible.fire({ content: { featuresLength: 1, getFeature: () => feature } }); s.postRender.fire()
  expect(feature.color).toEqual({ color: '#fbfbf9', alpha: 1 })
  expect(s.reports.at(-1)[0]).toEqual({ measured: 0, estimated: 0, unknown: 1 })
  s.renderer.setSite([[0,0],[2,0],[2,2],[0,2],[0,0]], true)
  s.tileVisible.fire({ content: { featuresLength: 1, getFeature: () => feature } })
  expect(feature.show).toBe(false)
  s.renderer.dispose(); expect(s.active.size).toBe(0); expect(s.destroyed()).toBe(true)
})

test('aggregate HLOD boxes hide while standing in for loading children and show at their own detail', async () => {
  const s = setup(); await Promise.resolve()
  Object.assign(s.tileset, { maximumScreenSpaceError: 16, memoryAdjustedScreenSpaceError: 16 })
  const feature = { show: true, color: undefined as unknown, hasProperty: (key: string) => key === 'componentCount', getProperty: () => undefined }
  const content = { featuresLength: 1, getFeature: () => feature }
  s.preRender.fire(); s.tileVisible.fire({ content, _screenSpaceError: 8 }); s.postRender.fire()
  expect(feature.show).toBe(true); expect(feature.color).toEqual({ color: '#fbfbf9', alpha: 1 })
  s.preRender.fire(); s.tileVisible.fire({ content, _screenSpaceError: 40 }); s.postRender.fire()
  expect(feature.show).toBe(false); expect(s.reports.at(-1)[0]).toEqual({ measured: 0, estimated: 0, unknown: 0 })
  // Final again: restyled (not left hidden by the stand-in pass).
  s.preRender.fire(); s.tileVisible.fire({ content, _screenSpaceError: 8 }); s.postRender.fire()
  expect(feature.show).toBe(true)
  // Fine aggregates (error <= 2 km) stand in visibly while detail loads; coarse ones stay hidden.
  s.tileVisible.fire({ content, _screenSpaceError: 40, geometricError: 1397 })
  expect(feature.show).toBe(true)
  s.tileVisible.fire({ content, _screenSpaceError: 40, geometricError: 8000 })
  expect(feature.show).toBe(false)
  // A failed child never replaces its parent: keep the parent instead of a permanent hole.
  s.tileVisible.fire({ content, _screenSpaceError: 40, children: [{ contentFailed: false, children: [{ contentFailed: true }] }] })
  expect(feature.show).toBe(true)
  // Cache pressure raises the refinement budget: the parent is final, so it must stay visible (no hole).
  s.tileset.memoryAdjustedScreenSpaceError = 731
  s.tileVisible.fire({ content, _screenSpaceError: 40 })
  expect(feature.show).toBe(true)
  const regional = { show: true, color: undefined as unknown, hasProperty: () => false, getProperty: (key: string) => ({ lon: 1, lat: 1, status: 'm' })[key as 'lon'] }
  s.tileVisible.fire({ content: { featuresLength: 1, getFeature: () => regional }, _screenSpaceError: 40 })
  expect(regional.show).toBe(true)
})

test('generalized HLOD (lodBlock + bbox) stands in while children load, blocks ignore the site, landmarks bbox-hide', async () => {
  const s = setup(); await Promise.resolve()
  Object.assign(s.tileset, { maximumScreenSpaceError: 16, memoryAdjustedScreenSpaceError: 16 })
  const props = (p: Record<string, number | string>) => ({ show: true, color: undefined as unknown, hasProperty: (k: string) => k in p, getProperty: (k: string) => p[k] })
  // A km-wide block whose first outline vertex is off-site, and a landmark whose lon/lat is off-site but bbox touches it.
  const block = props({ lon: 10, lat: 10, status: 'e', componentCount: 900, west: 0, south: 0, east: 10, north: 10, lodBlock: 1 })
  const landmark = props({ lon: 3, lat: 3, status: 'm', componentCount: 1, west: 3, south: 3, east: 4.5, north: 4.5, lodBlock: 0 })
  const content = { featuresLength: 2, getFeature: (i: number) => [block, landmark][i] }
  s.renderer.setSite([[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]], true)
  s.preRender.fire(); s.tileVisible.fire({ content, _screenSpaceError: 400, geometricError: 8000 }); s.postRender.fire()
  expect([block.show, landmark.show]).toEqual([true, false])
  expect(s.reports.at(-1)[0]).toEqual({ measured: 0, estimated: 0, unknown: 0 })
  s.renderer.setSite(null, false)
  s.preRender.fire(); s.tileVisible.fire({ content, _screenSpaceError: 400, geometricError: 8000 }); s.postRender.fire()
  expect([block.show, landmark.show]).toEqual([true, true])
  expect(s.reports.at(-1)[0]).toEqual({ measured: 1, estimated: 0, unknown: 0 }) // the block is not counted as one building
})

test('merged blocks never hide for the site (they span far beyond it), landmarks do, blocks are not counted, and only leaves mark first detail', async () => {
  performance.clearMarks('world-buildings-first-detail')
  const s = setup(); await Promise.resolve()
  const props = (p: Record<string, number | string>) => ({ show: true, color: undefined as unknown, hasProperty: (k: string) => k in p, getProperty: (k: string) => p[k] })
  // Block whose first outline vertex (lon/lat) is outside the site but whose bbox covers it.
  const block = props({ lon: 10, lat: 10, status: 'e', west: 0, south: 0, east: 10, north: 10, lodBlock: 1 })
  const far = props({ lon: 20, lat: 20, status: 'e', west: 20, south: 20, east: 30, north: 30, lodBlock: 1 })
  const landmark = props({ lon: 4, lat: 4, status: 'm', west: 3.5, south: 3.5, east: 4.5, north: 4.5, lodBlock: 0 })
  const root = { featuresLength: 3, getFeature: (i: number) => [landmark, block, far][i] }
  s.renderer.setSite([[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]], true)
  s.preRender.fire(); s.tileVisible.fire({ content: root, geometricError: 25 }); s.postRender.fire()
  expect([block.show, far.show, landmark.show]).toEqual([true, true, false])
  expect(s.reports.at(-1)[0]).toEqual({ measured: 0, estimated: 0, unknown: 0 })
  expect(performance.getEntriesByName('world-buildings-first-detail')).toHaveLength(0)
  s.renderer.setSite([[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]], false)
  s.tileVisible.fire({ content: root, geometricError: 25 })
  expect([block.show, far.show, landmark.show]).toEqual([true, true, true])
  const leaf = props({ lon: 5, lat: 5, status: 'm' })
  s.tileVisible.fire({ content: { featuresLength: 1, getFeature: () => leaf }, geometricError: 0 })
  expect(performance.getEntriesByName('world-buildings-first-detail')).toHaveLength(1)
})

test('frames keep coming while tiles load and stop once the tileset has loaded', async () => {
  const s = setup(); await Promise.resolve()
  let renders = 0
  ;(s.renderer as any).viewer.scene.requestRender = () => { renders++ }
  s.tileset.tilesLoaded = false; s.postRender.fire(); s.postRender.fire()
  expect(renders).toBe(2)
  s.tileset.tilesLoaded = true; s.postRender.fire()
  expect(renders).toBe(2)
  s.tileset.tilesLoaded = false; s.renderer.setShow(false); renders = 0; s.postRender.fire()
  expect(renders).toBe(0)
})

test('late tileset creation after unmount is destroyed without attaching', async () => {
  const s = setup(true)
  s.renderer.dispose(); s.resolve(); await Promise.resolve()
  expect(s.active.size).toBe(0); expect(s.destroyed()).toBe(true)
  expect(s.preRender.listeners.size).toBe(0); expect(s.postRender.listeners.size).toBe(0)
})
