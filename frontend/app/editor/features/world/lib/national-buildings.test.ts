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

test('late tileset creation after unmount is destroyed without attaching', async () => {
  const s = setup(true)
  s.renderer.dispose(); s.resolve(); await Promise.resolve()
  expect(s.active.size).toBe(0); expect(s.destroyed()).toBe(true)
  expect(s.preRender.listeners.size).toBe(0); expect(s.postRender.listeners.size).toBe(0)
})
