import { expect, test, beforeEach, afterEach } from 'bun:test'
import { coversTile, PrebuiltBuildings } from './prebuilt-buildings'
import { tileXY } from './building-geometry'

test('prepared roof lookup leaves courtyards open and still finds a separate annex', () => {
  const baked = Object.create(PrebuiltBuildings.prototype) as any
  const courtyard = { key: 'court', ring: [[0,0],[10,0],[10,10],[0,10],[0,0]],
    holes: [[[2,2],[8,2],[8,8],[2,8],[2,2]]], z:50, h:20 }
  baked.enabled=true; baked.shown=true; baked.hide=false
  baked.loaded=[{ fallbackReady:false, features:[courtyard] }]
  expect(baked.heightAt(1,1)).toBe(70)
  expect(baked.heightAt(5,5)).toBeUndefined()
  baked.loaded[0].features.push({ ring:[[4,4],[6,4],[6,6],[4,6],[4,4]],z:50,h:5 })
  expect(baked.heightAt(5,5)).toBe(55)
})

// Legacy installations have no small pointer yet; exercise their real 404 fallback.
let fetchDescriptor: PropertyDescriptor | undefined
beforeEach(() => {
  fetchDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'fetch')
  let implementation = globalThis.fetch
  Object.defineProperty(globalThis, 'fetch', { configurable: true,
    get: () => implementation,
    set: (next: typeof fetch) => { implementation = ((url: any, options?: any) =>
      String(url).endsWith('/latest.json') ? Promise.resolve(new Response('', { status:404 })) : next(url,options)) as typeof fetch },
  })
})
afterEach(() => { if (fetchDescriptor) Object.defineProperty(globalThis, 'fetch', fetchDescriptor) })

test('partial measured coverage never suppresses an unbaked neighbour or its coarse parent', () => {
  const region = { z: 14, x: 1, y: 1, coverage: ['16/4/4', '16/5/4', '16/4/5', '16/5/5'] }
  expect(coversTile(region, { z: 16, x: 4, y: 4, key: '' })).toBe(true)
  expect(coversTile(region, { z: 16, x: 6, y: 4, key: '' })).toBe(false)
  expect(coversTile(region, { z: 15, x: 2, y: 2, key: '' })).toBe(true)
  expect(coversTile(region, { z: 14, x: 1, y: 1, key: '' })).toBe(false)
})

test('travel evicts distant offscreen regions, protects visible coverage and reloads evicted regions', async () => {
  const event = { addEventListener: () => () => {} }
  const regions = Array.from({ length: 20 }, (_, x) => ({ id: String(x), z: 14, x, y: 1,
    url: `/region-${x}`, footprints: `/meta-${x}`, bounds: [x, 0, x + 0.9, 1] }))
  const original = globalThis.fetch
  globalThis.fetch = (async () => Response.json({ regions })) as typeof fetch
  const active = new Set<any>(), opened: string[] = []
  const scene = { preRender: event, postRender: event, requestRender() {}, primitives: {
    add(t: any) { active.add(t) }, remove(t: any) { active.delete(t) },
  } }
  const C = { Cesium3DTileset: { fromUrl: async (url: string) => {
    opened.push(url); return { url, tileVisible: event, tileFailed: event, allTilesLoaded: { addEventListener: (fn: () => void) => { queueMicrotask(fn) } } }
  } } }
  const baked = new PrebuiltBuildings({ scene }, C, () => {})
  const visit = async (x: number, end = x + 0.8) => {
    baked.setView([x + 0.1, 0.1, end, 0.9], { lon: x + 0.4, lat: 0.5 })
    await new Promise(resolve => setTimeout(resolve, 0))
  }
  try {
    for (let x = 0; x < 20; x++) await visit(x)
    expect(active.size).toBe(16)
    expect([...active].some(t => t.url === '/api/map-data/world-buildings/region-0')).toBe(false)
    expect(baked.owns({ z: 14, x: 19, y: 1, key: '' })).toBe(true)
    await visit(0)
    expect(opened.filter(url => url === '/api/map-data/world-buildings/region-0')).toHaveLength(2)
    expect(active.size).toBe(16)
    await visit(0, 19.9)
    expect(active.size).toBe(16)
    expect([...active].filter(t => t.show).length).toBe(16)
    await visit(0)
    expect(active.size).toBe(16)
  } finally { baked.dispose(); globalThis.fetch = original }
})

test('baked coverage never claims a coarse tile extending outside its region', () => {
  const region = { z: 14, x: 13976, y: 6335 }
  expect(coversTile(region, { z: 16, x: 55907, y: 25341, key: '' })).toBe(true)
  expect(coversTile(region, { z: 16, x: 55908, y: 25341, key: '' })).toBe(false)
  expect(coversTile(region, { z: 13, x: 6988, y: 3167, key: '' })).toBe(false)
})

test('only visible region manifests open; moving loads new coverage without fetching the catalog again', async () => {
  const event = { addEventListener: () => () => {} }
  const opened: string[] = []
  let catalogs = 0
  const original = globalThis.fetch
  globalThis.fetch = (async () => {
    catalogs++
    return Response.json({ regions: [
      { id: 'near', z: 14, x: 1, y: 1, url: '/near', bounds: [127, 37, 128, 38] },
      { id: 'far', z: 14, x: 2, y: 1, url: '/far', bounds: [129, 35, 130, 36] },
    ] })
  }) as typeof fetch
  const viewer = { scene: { preRender: event, postRender: event, requestRender() {}, primitives: { add() {}, remove() {} } } }
  const C = { Cesium3DTileset: { fromUrl: async (url: string) => {
    opened.push(url); return { tileVisible: event, tileFailed: event, allTilesLoaded: event }
  } } }
  const baked = new PrebuiltBuildings(viewer, C, () => {})
  try {
    baked.setView([127.2, 37.2, 127.3, 37.3], { lon: 127.25, lat: 37.25 })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(opened).toEqual(['/api/map-data/world-buildings/near'])
    baked.setView([129.2, 35.2, 129.3, 35.3], { lon: 129.25, lat: 35.25 })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(opened).toEqual(['/api/map-data/world-buildings/near', '/api/map-data/world-buildings/far'])
    expect(catalogs).toBe(1)
  } finally { baked.dispose(); globalThis.fetch = original }
})

test('flat mode and failed baked content release coverage back to the vector renderer', async () => {
  const event = () => {
    const listeners = new Set<(...args: any[]) => void>()
    return { addEventListener: (fn: (...args: any[]) => void) => { listeners.add(fn); return () => listeners.delete(fn) }, emit: (...args: any[]) => { for (const fn of listeners) fn(...args) } }
  }
  const tileset = { show: true, tileVisible: event(), tileFailed: event(), allTilesLoaded: event() }
  const scene = { preRender: event(), postRender: event(), requestRender() {}, primitives: { add() {}, remove() {} } }
  const original = globalThis.fetch
  globalThis.fetch = (async (url: string) => Response.json(url.endsWith('catalog.json')
    ? { regions: [{ z: 14, x: 13976, y: 6335, bounds: [127, 37, 128, 38], url: '/tile', footprints: '/footprints' }] } : [])) as typeof fetch
  const changes: boolean[] = []
  const baked = new PrebuiltBuildings({ scene }, { Cesium3DTileset: { fromUrl: async () => tileset },
    Color: { fromCssColorString: (hex: string) => ({ withAlpha: (alpha: number) => ({ hex, alpha }) }) } }, coverage => changes.push(Boolean(coverage)))
  const tile = { z: 16, x: 55907, y: 25341, key: '' }
  baked.setView([127, 37, 128, 38], { lon: 127.5, lat: 37.5 })
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(baked.owns(tile)).toBe(false)
    tileset.allTilesLoaded.emit()
    await Promise.resolve()
    expect(baked.owns(tile)).toBe(true)
    const unknown: any = { getProperty: (key: string) => key === 'status' ? 'u' : 127 }
    tileset.tileVisible.emit({ content: { featuresLength: 1, getFeature: () => unknown } })
    expect(unknown.color).toEqual({ hex: '#fbfbf9', alpha: 1 })
    expect(unknown.getProperty('status')).toBe('u')
    baked.setGround(false)
    expect(baked.owns(tile)).toBe(false)
    expect(tileset.show).toBe(false)
    baked.setGround(true)
    expect(baked.owns(tile)).toBe(true)
    tileset.tileFailed.emit({ message: 'offline' })
    await Promise.resolve()
    expect(baked.owns(tile)).toBe(false)
    expect(tileset.show).toBe(true)
    baked.setShow(false); baked.setShow(true)
    expect(tileset.show).toBe(true)
    const neighbour = { ...tile, x: tile.x - 1, key: 'neighbour' }
    baked.retireFailed([tile, neighbour], [tile])
    expect(tileset.show).toBe(true)
    baked.retireFailed([tile, neighbour], [tile, neighbour])
    expect(tileset.show).toBe(false)
    baked.setShow(false); baked.setShow(true)
    expect(tileset.show).toBe(false)
    expect(baked.error).toContain('offline')
    expect(changes.filter(Boolean)).toHaveLength(2)
  } finally { baked.dispose(); globalThis.fetch = original }
})

test('wide views admit only two unfinished tilesets and bound aggregate cache budgets', async () => {
  const event = { addEventListener: () => () => {} }
  const regions = Array.from({length:40},(_,x)=>({id:String(x),z:14,x,y:1,url:`/bounded-${x}`,footprints:`/meta-${x}`,bounds:[127+x*.001,37,127.001+x*.001,37.001]}))
  globalThis.fetch = (async()=>Response.json({regions})) as typeof fetch
  const opened: {ready:()=>void;options:any}[]=[]
  const scene={preRender:event,postRender:event,requestRender(){},primitives:{add(){},remove(){}}}
  const baked=new PrebuiltBuildings({scene},{Cesium3DTileset:{fromUrl:async (_url:string,options:any)=>{
    const item={ready:()=>{},options};opened.push(item)
    return {tileVisible:event,tileFailed:event,allTilesLoaded:{addEventListener(fn:()=>void){item.ready=fn}}}
  }}},()=>{})
  try {
    baked.setView([127,37,127.05,37.001],{lon:127.001,lat:37.0005})
    await new Promise(r=>setTimeout(r,0))
    expect(opened).toHaveLength(2)
    for(let cycle=0;cycle<20;cycle++){for(const item of opened)item.ready();await new Promise(r=>setTimeout(r,0))}
    expect(opened).toHaveLength(16)
    expect(opened.reduce((n,x)=>n+x.options.cacheBytes+x.options.maximumCacheOverflowBytes,0)).toBeLessThanOrEqual(256*1024*1024)
  } finally {baked.dispose()}
})

test('idle offscreen tilesets release admission without claiming drawn coverage', async () => {
  const original = globalThis.fetch
  const event = { addEventListener: () => () => {} }
  let postRender = () => {}
  const regions = Array.from({ length: 4 }, (_, x) => ({ id: String(x), z: 14, x, y: 1,
    url: `/idle-${x}`, bounds: [127 + x * .001, 37, 127.001 + x * .001, 37.001] }))
  globalThis.fetch = (async () => Response.json({ regions })) as typeof fetch
  let opened = 0
  const scene = { preRender: event, postRender: { addEventListener(fn: () => void) { postRender = fn; return () => {} } },
    requestRender() {}, primitives: { add() {}, remove() {} } }
  const baked = new PrebuiltBuildings({ scene }, { Cesium3DTileset: { fromUrl: async () => {
    opened++; return { tilesLoaded: true, tileVisible: event, tileFailed: event, allTilesLoaded: event }
  } } }, () => {})
  try {
    baked.setView([127, 37, 127.05, 37.001], { lon: 127.001, lat: 37.0005 })
    await new Promise(r => setTimeout(r, 0))
    expect(opened).toBe(2)
    postRender()
    await new Promise(r => setTimeout(r, 0))
    expect(opened).toBe(4)
    expect(baked.owns({ z: 14, x: 0, y: 1, key: '' })).toBe(false)
  } finally { baked.dispose(); globalThis.fetch = original }
})

test('moving after catalog expiry discovers new regions without replacing visible geometry', async () => {
  const event = { addEventListener: () => () => {} }
  const a = { id: 'a', z: 14, x: 1, y: 1, bounds: [127, 37, 128, 38], url: '/a', footprints: '/a-meta' }
  const b = { id: 'b', z: 14, x: 2, y: 1, bounds: [129, 35, 130, 36], url: '/b', footprints: '/b-meta' }
  const originalFetch = globalThis.fetch, originalNow = Date.now
  let now = originalNow(), calls = 0
  Date.now = () => now
  globalThis.fetch = (async () => {
    calls++
    return calls === 3 ? new Response('', { status: 503 }) : Response.json({ regions: calls === 1 ? [a] : [{ ...a, url: '/a-new' }, b] })
  }) as typeof fetch
  const opened: string[] = []
  const viewer = { scene: { preRender: event, postRender: event, requestRender() {}, primitives: { add() {}, remove() {} } } }
  const C = { Cesium3DTileset: { fromUrl: async (url: string) => {
    opened.push(url); return { tileVisible: event, tileFailed: event, allTilesLoaded: event }
  } } }
  const baked = new PrebuiltBuildings(viewer, C, () => {})
  const settle = () => new Promise(resolve => setTimeout(resolve, 0))
  try {
    baked.setView([127.1, 37.1, 127.2, 37.2], { lon: 127.15, lat: 37.15 })
    await settle()
    now += 61_000
    baked.setView([129.1, 35.1, 129.2, 35.2], { lon: 129.15, lat: 35.15 })
    baked.setView([129.1, 35.1, 129.2, 35.2], { lon: 129.15, lat: 35.15 })
    await settle()
    expect(calls).toBe(2)
    expect(opened).toEqual(['/api/map-data/world-buildings/a', '/api/map-data/world-buildings/b'])
    baked.setView([127.1, 37.1, 127.2, 37.2], { lon: 127.15, lat: 37.15 })
    await settle()
    expect(opened).not.toContain('/api/map-data/world-buildings/a-new')
    now += 61_000
    baked.setView([129.1, 35.1, 129.2, 35.2], { lon: 129.15, lat: 35.15 })
    await settle()
    expect(calls).toBe(3)
    expect(opened).toHaveLength(2)
  } finally { baked.dispose(); globalThis.fetch = originalFetch; Date.now = originalNow }
})

test('a transient manifest failure retries after cooldown without a reload or tight loop', async () => {
  const event = { addEventListener: () => () => {} }, originalFetch = globalThis.fetch, originalNow = Date.now
  let now = originalNow(), attempts = 0
  Date.now = () => now
  globalThis.fetch = (async () => Response.json({ regions: [{ id: 'r', z: 14, x: 1, y: 1, bounds: [127,37,128,38], url: '/retry', footprints: '/meta' }] })) as typeof fetch
  const scene = { preRender: event, postRender: event, requestRender() {}, primitives: { add() {}, remove() {} } }
  const baked = new PrebuiltBuildings({ scene }, { Cesium3DTileset: { fromUrl: async () => {
    attempts++
    if (attempts === 1) throw new Error('temporary outage')
    return { tileVisible: event, tileFailed: event, allTilesLoaded: event }
  } } }, () => {})
  const visit = () => baked.setView([127.1,37.1,127.2,37.2], { lon:127.15,lat:37.15 })
  try {
    visit(); await new Promise(resolve => setTimeout(resolve,0))
    visit(); await new Promise(resolve => setTimeout(resolve,0))
    expect(attempts).toBe(1)
    now += 5001
    visit(); await new Promise(resolve => setTimeout(resolve,0))
    expect(attempts).toBe(2)
  } finally { baked.dispose(); globalThis.fetch = originalFetch; Date.now = originalNow }
})

test('a partially baked leaf suppresses only buildings actually present in its drawn mesh', async () => {
  const event = () => {
    const listeners = new Set<(...args: any[]) => void>()
    return { addEventListener: (fn: (...args: any[]) => void) => { listeners.add(fn); return () => listeners.delete(fn) }, emit: (...args: any[]) => { for (const fn of listeners) fn(...args) } }
  }
  const tileset = { tileVisible: event(), tileFailed: event(), allTilesLoaded: event() }
  const scene = { preRender: event(), postRender: event(), requestRender() {}, primitives: { add() {}, remove() {} } }
  const original = globalThis.fetch
  const [x, y] = tileXY(127.1, 37.1)
  globalThis.fetch = (async () => Response.json({ regions: [{ id: 'partial', z: 14, x: Math.floor(x / 4), y: Math.floor(y / 4),
    bounds: [127,37,128,38], url: '/partial', footprints: '/meta', coverage: [], partialCoverage: [`16/${x}/${y}`] }] })) as typeof fetch
  const changes: boolean[] = []
  const baked = new PrebuiltBuildings({ scene }, { Cesium3DTileset: { fromUrl: async () => tileset },
    Color: { fromCssColorString: () => ({ withAlpha: () => ({}) }) } }, coverage => changes.push(Boolean(coverage)))
  const known = { key: 'known', pnu: '', ring: [[127.1,37.1]], h: 10, z: 5, s: 'm' as const }
  const properties: Record<string, string | number> = { key: 'known', status: 'm', lon: 127.1, lat: 37.1 }
  const feature: any = { getProperty: (key: string) => properties[key] }
  const tile = { content: { featuresLength: 1, getFeature: () => feature } }
  try {
    baked.setView([127,37,128,38], { lon:127.1,lat:37.1 })
    await new Promise(resolve => setTimeout(resolve,0))
    expect(baked.contains(known)).toBe(false)
    tileset.allTilesLoaded.emit(); tileset.tileVisible.emit(tile); scene.postRender.emit()
    await Promise.resolve()
    expect(baked.contains(known)).toBe(true)
    expect(baked.contains({ ...known, key: 'unbaked' })).toBe(false)
    expect(baked.owns({ z:16,x,y,key:'' })).toBe(false)
    expect(baked.contains({ ...known, key: `14/${Math.floor(x / 4)}/${Math.floor(y / 4)}/0` })).toBe(true)
    expect(baked.contains({ ...known, key: '14/other/0', ring: [[128,38]] })).toBe(false)
    const count = changes.filter(Boolean).length
    tileset.tileVisible.emit(tile); scene.postRender.emit(); await Promise.resolve()
    expect(changes.filter(Boolean)).toHaveLength(count)
    tileset.tileFailed.emit({ message:'offline' })
    expect(baked.contains(known)).toBe(false)
  } finally { baked.dispose(); globalThis.fetch = original }
})
