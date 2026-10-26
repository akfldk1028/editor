import { expect, test } from 'bun:test'
import { demTerrain } from './terrain'
import type { TerrainRevision } from './terrain-revision'

test('retired archive waits settle before wire completion without cancelling shared consumers or caching late answers', async () => {
  class Provider {
    tilingScheme = { tileXYToRectangle: () => ({ west: 127, east: 130, south: 37, north: 38 }),
      positionToTileXY: (p: any) => ({ x: Math.round(p.longitude), y: 1 }) }
    constructor(public options: any) {}
  }
  const C = { CustomHeightmapTerrainProvider: Provider, Math: { toDegrees: (n: number) => n },
    Cartographic: { fromDegrees: (longitude: number, latitude: number) => ({ longitude, latitude }) } }
  const requests = new Map<string, { calls: number; resolve: (height: number) => void }>()
  const answer = (height: number) => ({ heights: new Float32Array(1089).fill(height), sourceLevel: 20, revision: 'a'.repeat(64) })
  const provider = demTerrain(C, () => 0, () => null, () => {}, undefined, async () => null, () => {}, async key => {
    if (!key.startsWith('20/')) return answer(80)
    if (key === '20/129/1') return answer(93)
    const previous = requests.get(key)
    if (previous) { previous.calls++; return answer(222) }
    return new Promise(resolve => requests.set(key, { calls: 1, resolve: height => resolve(answer(height)) }))
  })
  let needed = true, sharedDone = false
  const old = [127, 128].map(lon => provider.sampleHeight(lon, 37.5, () => needed).catch((e: Error) => e.message))
  const shared = provider.sampleHeight(128, 37.5).then((height: number) => { sharedDone = true; return height })
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    needed = false; provider.pruneRequests()
    expect(await Promise.race([old[0], new Promise(resolve => setTimeout(() => resolve('blocked'), 100))])).toBe('terrain sample retired')
    expect(sharedDone).toBe(false)
    expect(requests.get('20/128/1')!.calls).toBe(1)
    expect(await provider.sampleHeight(129, 37.5)).toBe(93)
    requests.get('20/127/1')!.resolve(111)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(await provider.sampleHeight(127, 37.5)).toBe(222)
    requests.get('20/128/1')!.resolve(94)
    expect(await shared).toBe(94)
    expect(await old[1]).toBe('terrain sample retired')
  } finally {
    provider.dispose()
    for (const request of requests.values()) request.resolve(94)
    await Promise.allSettled([...old, shared])
  }
})

test('static terrain bypasses slow revision and computation queues and preserves missing samples', async () => {
  class Provider {
    tilingScheme = { tileXYToRectangle: () => ({ west:127,east:127.01,south:37,north:37.01 }), positionToTileXY: () => ({ x:1,y:1 }) }
    constructor(public options: any) {}
  }
  let revisionCalls=0, archiveCalls=0
  const C={CustomHeightmapTerrainProvider:Provider,Math:{toDegrees:(n:number)=>n},Cartographic:{fromDegrees:(longitude:number,latitude:number)=>({longitude,latitude})}}
  const provider=demTerrain(C,()=>10,()=>null,()=>{},undefined,async()=>{revisionCalls++;return null},()=>{},async()=>{
    archiveCalls++; const heights=new Float32Array(1089).fill(80); heights[0]=NaN
    return {heights,sourceLevel:17,revision:'a'.repeat(64)}
  })
  try {
    const tiles=Array.from({length:8},(_,i)=>provider.options.callback(i+1,1,17))
    expect(tiles.every(Boolean)).toBe(true)
    await Promise.all(tiles)
    expect(revisionCalls).toBe(0);expect(archiveCalls).toBe(8)
    expect(await provider.sampleHeight(127.005,37.005)).toBe(80)
    await expect(provider.sampleHeight(127,37.01)).rejects.toThrow('no measured terrain height')
  } finally {provider.dispose()}
})

function fixture(onError = (_message: string) => {}, focus: () => { lon: number; lat: number } | null = () => null,
  published: (key: string) => Promise<Float32Array | undefined> = async () => undefined,
  revisionReader: () => Promise<TerrainRevision | null> = async () => ({ revision: 'test-revision', vrt_sha256: 'test-vrt' })) {
  class Provider {
    tilingScheme = { tileXYToRectangle: () => ({ west: 127, east: 127.01, south: 37, north: 37.01 }),
      positionToTileXY: () => ({ x: 1, y: 1 }) }
    constructor(public options: any) {}
  }
  return demTerrain({ CustomHeightmapTerrainProvider: Provider, Math: { toDegrees: (n: number) => n },
    Cartographic: { fromDegrees: (longitude: number, latitude: number) => ({ longitude, latitude }) } }, () => 0, focus, onError, published, revisionReader)
}

test('published measured terrain supplies camera height without a computation API', async () => {
  const original = globalThis.fetch
  globalThis.fetch = (async () => { throw new Error('unexpected API request') }) as typeof fetch
  const provider = fixture(() => {}, () => null, async () => new Float32Array(1089).fill(93.25))
  try { expect(await provider.sampleHeight(127.005, 37.005)).toBe(93.25) }
  finally { provider.dispose(); globalThis.fetch = original }
})

test('pinned publication remains available when live revision lookup fails', async () => {
  const original = globalThis.fetch
  globalThis.fetch = (async () => { throw new Error('unexpected computation API request') }) as typeof fetch
  const provider = fixture(() => {}, () => null, async () => new Float32Array(1089).fill(93.25), async () => null)
  try { expect(await provider.sampleHeight(127.005, 37.005)).toBe(93.25) }
  finally { provider.dispose(); globalThis.fetch = original }
})

test('zooming into a new target prioritizes its measured terrain over old camera samples', async () => {
  const original = globalThis.fetch
  let focus = { lon: 127.0015, lat: 37.005 }
  const provider = fixture(() => {}, () => focus)
  provider.tilingScheme.tileXYToRectangle = (x: number) => ({ west: 127 + x / 1000, east: 127 + (x + 1) / 1000, south: 37, north: 37.01 })
  const requests: { west: number; resolve(response: Response): void }[] = []
  globalThis.fetch = ((url: string) => new Promise<Response>(resolve => {
    requests.push({ west: Number(new URL(url, 'http://localhost').searchParams.get('west')), resolve })
  })) as typeof fetch
  const response = () => Response.json({ heights: Array(1089).fill(93) })
  const pending = [10, 11, 1, 20].map(x => provider.options.callback(x, 1, 17, true))
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    focus = { lon: 127.0205, lat: 37.005 }
    requests[0]!.resolve(response())
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requests[2]!.west).toBeCloseTo(127.020, 6)
  } finally {
    provider.dispose()
    for (const request of requests) request.resolve(response())
    await Promise.all(pending)
    globalThis.fetch = original
  }
})
test('source resolution is available through level 17 and answered tiles are reused', async () => {
  const original = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => { calls++; return Response.json({ heights: Array(1089).fill(42) }) }) as typeof fetch
  const provider = fixture()
  try {
    for (const level of [11, 15, 17]) {
      expect((await provider.options.callback(1, 1, level))[0]).toBe(42)
      expect((await provider.options.callback(1, 1, level))[0]).toBe(42)
    }
    expect(calls).toBe(3)
    expect(provider.options.callback(1, 1, 18)).toBeUndefined()
    expect(provider.getTileDataAvailable(1, 1, 17)).toBe(true)
    expect(provider.getTileDataAvailable(1, 1, 18)).toBe(false)
  } finally { provider.dispose(); globalThis.fetch = original }
})

test('retired measured jobs release active slots without cancelling another live consumer', async () => {
  const original = globalThis.fetch
  const errors: string[] = []
  const provider = fixture(message => errors.push(message))
  provider.tilingScheme.positionToTileXY = (p: any) => ({ x: Math.round(p.longitude), y: 1 })
  const requests: { aborted: boolean; resolve(response: Response): void }[] = []
  globalThis.fetch = ((_url: string, options: any) => new Promise<Response>((resolve, reject) => {
    const entry = { aborted: false, resolve }; requests.push(entry)
    options.signal.addEventListener('abort', () => { entry.aborted = true; reject(new Error('aborted')) })
  })) as typeof fetch
  let oldView = true
  const old = [127, 128].map(lon => provider.sampleHeight(lon, 37, () => oldView).catch((e: Error) => e.message))
  const shared = provider.sampleHeight(128, 37)
  const next = provider.sampleHeight(129, 37)
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requests).toHaveLength(2)
    oldView = false
    provider.pruneRequests()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requests[0]!.aborted).toBe(true)
    expect(requests[1]!.aborted).toBe(false)
    expect(requests).toHaveLength(3)
    requests[1]!.resolve(Response.json({ heights: Array(1089).fill(93) }))
    requests[2]!.resolve(Response.json({ heights: Array(1089).fill(93) }))
    expect(await shared).toBe(93)
    expect(await next).toBe(93)
    expect(await Promise.all(old)).toEqual(['terrain sample retired', 'terrain sample retired'])
    expect(errors).toHaveLength(0)
  } finally {
    provider.dispose()
    for (const request of requests) request.resolve(Response.json({ heights: Array(1089).fill(93) }))
    await Promise.all([...old, shared, next])
    globalThis.fetch = original
  }
})

test('a persistent measured cache hit does not wait behind two active HTTP requests', async () => {
  const original = globalThis.fetch
  const originalCaches = Object.getOwnPropertyDescriptor(globalThis, 'caches')
  const originalLocation = Object.getOwnPropertyDescriptor(globalThis, 'location')
  Object.defineProperty(globalThis, 'location', { configurable: true, value: { origin: 'http://localhost' } })
  Object.defineProperty(globalThis, 'caches', { configurable: true, value: { open: async () => ({
    match: async (url: string) => decodeURIComponent(url).endsWith('/17/129/1')
      ? Response.json(Array(1089).fill(42), { headers: { 'x-world-saved-at': String(Date.now()) } }) : undefined,
  }) } })
  const provider = fixture()
  provider.tilingScheme.positionToTileXY = (p: any) => ({ x: Math.round(p.longitude), y: 1 })
  let calls = 0
  globalThis.fetch = ((_url: string, options: any) => new Promise<Response>((_resolve, reject) => {
    calls++
    options.signal.addEventListener('abort', () => reject(new Error('aborted')))
  })) as typeof fetch
  const active = [127, 128].map(lon => provider.sampleHeight(lon, 37).catch(() => null))
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(calls).toBe(2)
    const result = await Promise.race([provider.sampleHeight(129, 37).catch(() => null),
      new Promise(resolve => setTimeout(() => resolve('blocked'), 100))])
    expect(result).toBe(42)
    expect(calls).toBe(2)
  } finally {
    provider.dispose(); await Promise.all(active)
    globalThis.fetch = original
    if (originalCaches) Object.defineProperty(globalThis, 'caches', originalCaches); else Reflect.deleteProperty(globalThis, 'caches')
    if (originalLocation) Object.defineProperty(globalThis, 'location', originalLocation); else Reflect.deleteProperty(globalThis, 'location')
  }
})

test('retiring a queued measured job settles immediately while both live network slots remain occupied', async () => {
  const original = globalThis.fetch
  const provider = fixture()
  provider.tilingScheme.positionToTileXY = (p: any) => ({ x: Math.round(p.longitude), y: 1 })
  let calls = 0, needed = true
  globalThis.fetch = ((_url: string, options: any) => new Promise<Response>((_resolve, reject) => {
    calls++; options.signal.addEventListener('abort', () => reject(new Error('aborted')))
  })) as typeof fetch
  const active = [127, 128].map(lon => provider.sampleHeight(lon, 37).catch(() => null))
  const queued = provider.sampleHeight(129, 37, () => needed).catch((e: Error) => e.message)
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    needed = false; provider.pruneRequests()
    expect(await Promise.race([queued, new Promise(resolve => setTimeout(() => resolve('blocked'), 100))])).toBe('terrain sample retired')
    expect(calls).toBe(2)
  } finally { provider.dispose(); await Promise.all([...active, queued]); globalThis.fetch = original }
})

test('camera and buildings share a fixed resolution measured height request; fallback is not a datum', async () => {
  const original = globalThis.fetch
  const provider = fixture()
  let calls = 0
  globalThis.fetch = (async () => { calls++; return Response.json({ heights: Array(1089).fill(93) }) }) as typeof fetch
  try {
    expect(await Promise.all([provider.sampleHeight(127.005, 37.005), provider.sampleHeight(127.006, 37.006)])).toEqual([93, 93])
    expect(calls).toBe(1)
    provider.dispose()
    await expect(provider.sampleHeight(127.005, 37.005)).rejects.toThrow('terrain unavailable')
  } finally { provider.dispose(); globalThis.fetch = original }
})

test('invalid DEM values are reported and never cached as measured terrain', async () => {
  const original = globalThis.fetch, errors: string[] = []
  const provider = fixture(message => errors.push(message))
  let calls = 0
  globalThis.fetch = (async () => Response.json({ heights: Array(1089).fill(++calls === 1 ? null : 42) })) as typeof fetch
  try {
    expect((await provider.options.callback(1, 1, 17))[0]).toBe(0)
    expect(errors).toHaveLength(1)
    expect((await provider.options.callback(1, 1, 17))[0]).toBe(42)
    expect(calls).toBe(2)
  } finally { provider.dispose(); globalThis.fetch = original }
})

test('missing terrain coverage is not retried as a transient server outage', async () => {
  const original = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => { calls++; return new Response('', { status: 404 }) }) as typeof fetch
  const provider = fixture()
  try {
    expect((await provider.options.callback(1, 1, 17))[0]).toBe(0)
    expect(calls).toBe(1)
    await expect(provider.sampleHeight(127.005, 37.005)).rejects.toThrow('no measured terrain height')
  } finally { provider.dispose(); globalThis.fetch = original }
})

test('disposal aborts active DEM requests and drains queued requests without fetching', async () => {
  const original = globalThis.fetch, errors: string[] = []
  const provider = fixture(message => errors.push(message))
  let calls = 0, aborted = 0
  globalThis.fetch = ((_url: any, options: any) => {
    calls++
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => { aborted++; reject(new Error('aborted')) }))
  }) as typeof fetch
  try {
    const requests = [1, 2, 3].map(x => provider.options.callback(x, 1, 17))
    expect(requests[2]).toBeUndefined()
    await new Promise(resolve => setTimeout(resolve, 0))
    provider.dispose()
    await Promise.all(requests)
    expect(calls).toBe(2)
    expect(aborted).toBe(2)
    expect(errors).toHaveLength(0)
  } finally { provider.dispose(); globalThis.fetch = original }
})

test('a measured-height lookup promotes an already queued display tile without duplicating its request', async () => {
  const original = globalThis.fetch
  const provider = fixture()
  provider.tilingScheme.tileXYToRectangle = (x: number) => ({ west: 127 + x / 1000, east: 127 + (x + 1) / 1000, south: 37, north: 37.01 })
  const requests: { west: number; resolve(response: Response): void }[] = []
  globalThis.fetch = ((url: string) => new Promise<Response>(resolve => {
    requests.push({ west: Number(new URL(url, 'http://localhost').searchParams.get('west')), resolve })
  })) as typeof fetch
  const response = () => Response.json({ heights: Array(1089).fill(93) })
  const displayed = [10, 11, 2, 1].map(x => provider.options.callback(x, 1, 17))
  const sampled = provider.sampleHeight(127.0015, 37.005).catch((error: Error) => error)
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requests).toHaveLength(2)
    requests[0]!.resolve(response())
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requests[2]!.west).toBeCloseTo(127.001, 6)
    requests[2]!.resolve(response())
    expect(await sampled).toBe(93)
    expect(requests.filter(request => Math.abs(request.west - 127.001) < 1e-8)).toHaveLength(1)
  } finally {
    provider.dispose()
    for (const request of requests) request.resolve(response())
    await Promise.all([...displayed, sampled])
    globalThis.fetch = original
  }
})


test('refresh isolates persistent terrain by live revision and bypasses it when revision is unavailable', async () => {
  const original = globalThis.fetch
  const originalCaches = Object.getOwnPropertyDescriptor(globalThis, 'caches')
  const originalLocation = Object.getOwnPropertyDescriptor(globalThis, 'location')
  const saved = new Map<string, Response>()
  Object.defineProperty(globalThis, 'location', { configurable: true, value: { origin: 'http://localhost' } })
  Object.defineProperty(globalThis, 'caches', { configurable: true, value: { open: async () => ({
    match: async (url: string) => saved.get(url)?.clone(),
    put: async (url: string, response: Response) => { saved.set(url, response) },
    keys: async () => [...saved.keys()], delete: async () => true,
  }) } })
  let liveRevision = 'old', height = 12, calls = 0, checks = 0
  globalThis.fetch = (async () => { calls++; return Response.json({ heights: Array(1089).fill(height) }) }) as typeof fetch
  const revision = async () => { checks++; return { revision: liveRevision, vrt_sha256: 'vrt' } }
  const sample = async (reader: () => Promise<TerrainRevision | null> = revision) => {
    const provider = fixture(() => {}, () => null, async () => undefined, reader)
    try { return await provider.sampleHeight(127.005, 37.005) } finally { provider.dispose() }
  }
  try {
    expect(await sample()).toBe(12)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(await sample()).toBe(12)
    expect(calls).toBe(1)
    liveRevision = 'new'; height = 27
    expect(await sample()).toBe(27)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(await sample()).toBe(27)
    expect(calls).toBe(2)
    height = 39
    expect(await sample(async () => null)).toBe(39)
    expect(calls).toBe(3)
    expect(checks).toBe(4)
  } finally {
    globalThis.fetch = original
    if (originalCaches) Object.defineProperty(globalThis, 'caches', originalCaches); else Reflect.deleteProperty(globalThis, 'caches')
    if (originalLocation) Object.defineProperty(globalThis, 'location', originalLocation); else Reflect.deleteProperty(globalThis, 'location')
  }
})
