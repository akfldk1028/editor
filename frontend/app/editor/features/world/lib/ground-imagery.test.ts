import { expect, test } from 'bun:test'
import { createGroundImageryProvider, groundRangeSource, prepareGroundImagery, validateGroundImagery, type GroundImageryLayer } from './ground-imagery'
import { TileType, type Header } from 'pmtiles'

const layer: GroundImageryLayer = { kind: 'roads', url: '/api/map-data/world-ground/roads.pmtiles', sha256: 'a'.repeat(64), bounds: [124, 33, 132, 39], minLevel: 0, maxLevel: 12, credit: 'NGII display only' }
const header = { tileType: TileType.Png, minZoom: 0, maxZoom: 12, minLon: 124, minLat: 33, maxLon: 132, maxLat: 39 } as Header
const C = { Rectangle: { fromDegrees: (...bounds: number[]) => bounds }, WebMercatorTilingScheme: class {}, Credit: class { constructor(public text: string) {} }, Event: class {} }
const canvas = () => ({ width: 0, height: 0, getContext: () => ({ drawImage() {} }) })
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
const png = () => { const bytes = new Uint8Array(29), v = new DataView(bytes.buffer); v.setUint32(0, 0x89504e47); v.setUint32(4, 0x0d0a1a0a); v.setUint32(8, 13); v.setUint32(12, 0x49484452); v.setUint32(16, 256); v.setUint32(20, 256); bytes[24] = 8; bytes[25] = 6; return bytes.buffer }
const descriptor = (layers = [layer]) => ({ schema: 'world-ground/imagery-v1', layers })

test('descriptor strictly validates road-only layer identities and orders landcover below roads', () => {
  expect(validateGroundImagery(descriptor([layer, { ...layer, kind: 'landcover' }])).map(x => x.kind)).toEqual(['landcover', 'roads'])
  for (const change of [ { kind: 'buildings' }, { bounds: [132,33,124,39] }, { minLevel: 13 }, { maxLevel: 13 }, { sha256: 'bad' }, { url: 'file:///roads.pmtiles' }, { url: '//other/roads.pmtiles' }, { surprise: true } ]) {
    expect(() => validateGroundImagery(descriptor([{ ...layer, ...change } as GroundImageryLayer]))).toThrow()
  }
  expect(() => validateGroundImagery(descriptor([layer, layer]))).toThrow()
})

test('only missing descriptor404 is optional, with no API fallback', async () => {
  const urls: string[] = []
  const result = await prepareGroundImagery(C, { get: async url => { urls.push(url); return new Response(null, { status: 404 }) } })
  expect(result.layers).toEqual([]);expect(urls).toEqual(['/api/map-data/world-ground/latest.json']);result.dispose()
  await expect(prepareGroundImagery(C, { get: async () => new Response(null, { status: 503 }) })).rejects.toThrow('503')
})

test('range source requires206/exactContentRange and preserves ETag identity', async () => {
  let seen = '', tag = 'one'
  const source = groundRangeSource(layer, new AbortController().signal, async (_url, init) => {
    seen = (init!.headers as Record<string,string>).Range
    return new Response(new Uint8Array([1,2,3]), { status: 206, headers: { 'Content-Range': 'bytes 4-6/7', ETag: tag } })
  })
  expect(new Uint8Array((await source.getBytes(4,10)).data)).toEqual(new Uint8Array([1,2,3]));expect(seen).toBe('bytes=4-13')
  tag = 'two';await expect(source.getBytes(4,10)).rejects.toThrow('ETag')
  for (const response of [new Response('fullfile'), new Response('bad', { status:206,headers:{'Content-Range':'bytes 0-2/7'} })]) {
    const broken = groundRangeSource(layer,new AbortController().signal,async()=>response)
    await expect(broken.getBytes(4,3)).rejects.toThrow()
  }
})

test('providers validate exact header bounds and return transparent missing/outside tiles', async () => {
  let reads=0
  const provider = await createGroundImageryProvider(C,layer,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>header,getZxy:async()=>{reads++;return undefined}})})
  expect(provider.hasAlphaChannel).toBe(true);expect(provider.rectangle).toEqual(layer.bounds)
  expect((await provider.requestImage(0,0,0))!.width).toBe(256)
  await provider.requestImage(0,0,12);expect(reads).toBe(1);provider.dispose()
  await expect(createGroundImageryProvider(C,layer,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>({...header,minLon:123}),getZxy:async()=>undefined})})).rejects.toThrow('header')
})

test('decode closes bitmap after canvas copy and does not expose a closed bitmap to Cesium', async () => {
  let closes=0,draws=0
  const provider = await createGroundImageryProvider(C,layer,new AbortController().signal,{canvas:()=>({width:0,height:0,getContext:()=>({drawImage(){draws++}})}),
    archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:png()})}),decode:async()=>({width:256,height:256,close(){closes++}})})
  const image = await provider.requestImage(0,0,0)
  expect(image!.width).toBe(256);expect(draws).toBe(1);expect(closes).toBe(1)
  provider.dispose();expect(closes).toBe(1)
})

test('at most4 tasks run, cancelled late decodes close safely and slots remain bounded', async () => {
  const waiting = deferred<{width:number;height:number;close():void}>();let decodes=0,closed=0,draws=0
  const provider = await createGroundImageryProvider(C,layer,new AbortController().signal,{canvas:()=>({width:0,height:0,getContext:()=>({drawImage(){draws++}})}),
    archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:png()})}),decode:async()=>{decodes++;return waiting.promise}})
  const tasks=Array.from({length:4},()=>provider.requestImage(0,0,0)!)
  expect(provider.requestImage(0,0,0)).toBeUndefined()
  await Promise.resolve();await Promise.resolve();expect(decodes).toBe(4)
  provider.dispose();await Promise.all(tasks.map(task=>expect(task).rejects.toThrow()))
  waiting.resolve({width:256,height:256,close(){closed++}})
  await Promise.resolve();await Promise.resolve();await Promise.resolve()
  expect(closed).toBe(4);expect(draws).toBe(0);expect(provider.requestImage(0,0,0)).toBeUndefined()
})

test('viewer disposed during descriptor or header preparation never receives late providers', async () => {
  const cancelled = new AbortController(), pending = deferred<Response>()
  const ready=prepareGroundImagery(C,{signal:cancelled.signal,get:()=>pending.promise})
  cancelled.abort();pending.resolve(Response.json(descriptor()))
  await expect(ready).rejects.toThrow()
  const disposed = new AbortController(), late=deferred<Header>()
  const loading=createGroundImageryProvider(C,layer,disposed.signal,{canvas,archive:()=>({getHeader:()=>late.promise,getZxy:async()=>undefined})})
  disposed.abort();await expect(loading).rejects.toThrow();late.resolve(header)
})

test('malformed PNG and oversized response do not reach bitmap decoding', async () => {
  let decodes=0
  const provider=await createGroundImageryProvider(C,layer,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:new ArrayBuffer(4)})}),decode:async()=>{decodes++;throw Error('unexpected')}})
  await expect(provider.requestImage(0,0,0)!).rejects.toThrow('RGBA');expect(decodes).toBe(0);provider.dispose()
  const source=groundRangeSource(layer,new AbortController().signal,async()=>new Response(new Uint8Array(5),{status:206,headers:{'Content-Range':'bytes 0-2/3'}}))
  await expect(source.getBytes(0,3)).rejects.toThrow('large')
})
