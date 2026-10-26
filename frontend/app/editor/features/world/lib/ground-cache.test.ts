import { expect, test } from 'bun:test'
import { cachedGround, refreshGroundBoundaries } from './ground-cache'

test('legacy full fill returns first, boundary refresh updates cache, preview never refreshes', async () => {
  const original=globalThis.fetch
  const old:any={status:'ok',features:{type:'FeatureCollection',features:[{properties:{id:'parcel',layer:'ground'},geometry:{type:'Polygon',coordinates:[]}}]}}
  const fresh:any=structuredClone(old)
  fresh.features.features[0].properties.parcel_boundary={type:'MultiLineString',coordinates:[]}
  let finish!:(r:Response)=>void,calls=0
  globalThis.fetch=(async()=>{calls++;return calls===1?Response.json(old):new Promise<Response>(resolve=>{finish=resolve})}) as typeof fetch
  try {
    const first=await cachedGround(37.161,127.161,320,'full')
    expect(first).toEqual(old)
    expect(await refreshGroundBoundaries(37.161,127.161,320,'roads',first)).toBeUndefined()
    expect(calls).toBe(1)
    const updating=refreshGroundBoundaries(37.161,127.161,320,'full',first)
    expect(await cachedGround(37.161,127.161,320,'full')).toEqual(old)
    finish(Response.json(fresh))
    expect(await updating).toEqual(fresh)
    expect(await cachedGround(37.161,127.161,320,'full')).toEqual(fresh)
    expect(await refreshGroundBoundaries(37.161,127.161,320,'full',fresh)).toBeUndefined()
    expect(calls).toBe(2)
  } finally {globalThis.fetch=original}
})

test('aborted or failed boundary refresh preserves existing fill and never caches stale replies', async () => {
  const original=globalThis.fetch
  const old:any={status:'ok',features:{type:'FeatureCollection',features:[{properties:{layer:'ground'}}]}}
  const fresh:any={status:'ok',features:{type:'FeatureCollection',features:[]}}
  let finish!:(r:Response)=>void,calls=0
  globalThis.fetch=(async()=>{calls++;return calls===1?Response.json(old):new Promise<Response>(resolve=>{finish=resolve})}) as typeof fetch
  try {
    await cachedGround(37.162,127.162,320,'full')
    const controller=new AbortController()
    const updating=refreshGroundBoundaries(37.162,127.162,320,'full',old,controller.signal)
    controller.abort(new Error('retired')); finish(Response.json(fresh))
    await expect(updating).rejects.toThrow('retired')
    expect(await cachedGround(37.162,127.162,320,'full')).toEqual(old)
    globalThis.fetch=(async()=>{throw new Error('offline')}) as typeof fetch
    await expect(refreshGroundBoundaries(37.162,127.162,320,'full',old)).rejects.toThrow('offline')
    expect(await cachedGround(37.162,127.162,320,'full')).toEqual(old)
  } finally {globalThis.fetch=original}
})

test('roads and full detail have separate caches, repeated views reuse successful cells', async () => {
  const original = globalThis.fetch, urls: string[] = []
  globalThis.fetch = (async (url: any) => { urls.push(String(url)); return Response.json({ status: 'ok', features: { features: [] } }) }) as typeof fetch
  try {
    for (const detail of ['roads', 'full', 'roads', 'full'] as const) await cachedGround(37.11, 127.11, 320, detail)
    expect(urls).toHaveLength(2)
    expect(urls[0]).toContain('detail=roads')
    expect(urls[1]).toContain('detail=full')
  } finally { globalThis.fetch = original }
})

test('needs_evidence is retried and aborted callers do not draw even cached data', async () => {
  const original = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => Response.json(++calls === 1 ? { status: 'needs_evidence', reason: 'busy' } : { status: 'ok' })) as typeof fetch
  try {
    await expect(cachedGround(37.12, 127.12, 320, 'roads')).rejects.toThrow('busy')
    await cachedGround(37.12, 127.12, 320, 'roads')
    const controller = new AbortController()
    controller.abort()
    await expect(cachedGround(37.12, 127.12, 320, 'roads', controller.signal)).rejects.toThrow()
    expect(calls).toBe(2)
  } finally { globalThis.fetch = original }
})

test('leaving a published cell releases the caller before its shared file finishes', async () => {
  const original = globalThis.fetch
  let release!: (response: Response) => void
  const file = 'c'.repeat(64) + '.json'
  globalThis.fetch = (async (url: any) => String(url).endsWith('catalog.json')
    ? Response.json({ cells: { '9432:25423': { file, sampledAt: new Date().toISOString() } } })
    : new Promise<Response>(resolve => { release = resolve })) as typeof fetch
  const controller = new AbortController()
  const request = cachedGround(37.73,127.1175,320,'full',controller.signal)
  try {
    await new Promise(resolve => setTimeout(resolve, 0))
    controller.abort(new Error('left view'))
    await expect(request).rejects.toThrow('left view')
  } finally {
    release?.(Response.json({ status:'ok',features:{type:'FeatureCollection',features:[]} }))
    await new Promise(resolve => setTimeout(resolve, 0))
    globalThis.fetch = original
  }
})

test('outer cache cannot extend the absolute freshness of a published snapshot', async () => {
  const original = globalThis.fetch, originalNow = Date.now
  let now = originalNow(), calls = 0
  Date.now = () => now
  globalThis.fetch = (async () => {
    calls++
    return Response.json({ status: 'ok', displaySnapshot: { sampledAt: new Date(now).toISOString(), expiresAt: now + 1000 } })
  }) as typeof fetch
  try {
    await cachedGround(37.13, 127.13, 320, 'full')
    await cachedGround(37.13, 127.13, 320, 'full')
    expect(calls).toBe(1)
    now += 1001
    await cachedGround(37.13, 127.13, 320, 'full')
    expect(calls).toBe(2)
  } finally { globalThis.fetch = original; Date.now = originalNow }
})

test('partial source gaps are drawable but retried instead of cached as complete', async () => {
  const original = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => { calls++; return Response.json({ status: 'ok', gaps: ['roads unavailable'] }) }) as typeof fetch
  try {
    await cachedGround(37.14, 127.14, 320, 'full')
    await cachedGround(37.14, 127.14, 320, 'full')
    expect(calls).toBe(2)
  } finally { globalThis.fetch = original }
})
