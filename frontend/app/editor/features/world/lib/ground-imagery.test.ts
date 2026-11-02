import { expect, test } from 'bun:test'
import { createGroundImageryProvider, groundParallel, groundRangeSource, prepareGroundImagery, validateGroundImagery, roadTextureSource, type GroundImageryLayer } from './ground-imagery'
import { TileType, type Header } from 'pmtiles'

const layer: GroundImageryLayer = { kind: 'roads', url: '/api/map-data/world-ground/roads.pmtiles', sha256: 'a'.repeat(64), bounds: [124, 33, 132, 39], minLevel: 0, maxLevel: 12, credit: 'NGII display only' }
const header = { tileType: TileType.Png, minZoom: 0, maxZoom: 12, minLon: 124, minLat: 33, maxLon: 132, maxLat: 39 } as Header
const C = { Rectangle: { fromDegrees: (...bounds: number[]) => bounds }, WebMercatorTilingScheme: class {}, Credit: class { constructor(public text: string) {} }, Event: class {} }
const canvas = () => ({ width: 0, height: 0, getContext: () => ({ drawImage() {} }) })
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
const png = (colour = 6) => { const bytes = new Uint8Array(29), v = new DataView(bytes.buffer); v.setUint32(0, 0x89504e47); v.setUint32(4, 0x0d0a1a0a); v.setUint32(8, 13); v.setUint32(12, 0x49484452); v.setUint32(16, 256); v.setUint32(20, 256); bytes[24] = 8; bytes[25] = colour; return bytes.buffer }
const descriptor = (layers = [layer]) => ({ schema: 'world-ground/imagery-v1', layers })

test('raw road texture restores transparent RGB while preserving all visible bytes and alpha', () => {
 const rgba=new Uint8ClampedArray(256*256*4);rgba.set([206,205,199,255],4);rgba.set([207,203,199,64],8)
 const before=rgba.slice(),source=roadTextureSource(rgba)!
 expect(source.arrayBufferView).toBeInstanceOf(Uint8Array)
 expect([...source.arrayBufferView.slice(0,4)]).toEqual([206,205,199,0])
 expect(source.arrayBufferView.slice(4,12)).toEqual(new Uint8Array(before.slice(4,12)))
 expect([...rgba].filter((_,i)=>i%4===3)).toEqual([...before].filter((_,i)=>i%4===3))
 const colored=before.slice();colored.set([20,90,10,255],12);const original=colored.slice()
 expect(roadTextureSource(colored)).toBeUndefined();expect(colored).toEqual(original)
 expect(roadTextureSource(new Uint8ClampedArray(256*256*4))).toBeUndefined()
 expect(()=>roadTextureSource(new Uint8ClampedArray(4))).toThrow('length')
})

test('only roads return Cesium typed texture sources, with bitmap ownership closed once', async () => {
 let closes=0,reads=0
 const dependencies={canvas:()=>({width:0,height:0,getContext:()=>({drawImage(){},getImageData(){reads++;const data=new Uint8ClampedArray(256*256*4);data.set([206,205,199,255],4);return{data}}})}),
  archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:png()})}),decode:async()=>({width:256,height:256,close(){closes++}})}
 const roads=await createGroundImageryProvider(C,layer,new AbortController().signal,dependencies)
 const image=await roads.requestImage(0,0,0)
 expect(image && 'arrayBufferView' in image).toBe(true);expect(closes).toBe(1);expect(reads).toBe(1);roads.dispose()
 const cover=await createGroundImageryProvider(C,{...layer,kind:'landcover'},new AbortController().signal,dependencies)
 const other=await cover.requestImage(0,0,0)
 expect(other && 'arrayBufferView' in other).toBe(false);expect(reads).toBe(1);expect(closes).toBe(2);cover.dispose()
})

test('coverage bounds strictly validate1..64 finite WebMercator rectangles', () => {
  const coverageBounds: GroundImageryLayer['coverageBounds'] = [[125.77,36.92,126.80,37.66], [130.8,37.4,131,37.6]]
  expect(validateGroundImagery(descriptor([{...layer,coverageBounds}]))[0]!.coverageBounds).toEqual(coverageBounds)
  expect(validateGroundImagery(descriptor([{...layer,coverageBounds:Array.from({length:64},()=>[125,34,126,35])}]))).toHaveLength(1)
  for (const bad of [undefined,null,[],new Array(1),Array.from({length:65},()=>[125,34,126,35]),[[125,34,126]],[[125,34,NaN,35]],[[125,34,Infinity,35]],[[126,34,125,35]],[[125,35,126,35]],[[-181,0,10,20]],[[-10,-86,10,20]],[[-10,0,181,20]],[[-10,0,10,86]],[['125',34,126,35]]]) {
    expect(()=>validateGroundImagery(descriptor([{...layer,coverageBounds:bad} as GroundImageryLayer]))).toThrow('coverage')
  }
})

test('coverage helper keeps island gaps and leaves archive header bounds unchanged', async () => {
  const dependencies={canvas,archive:()=>({getHeader:async()=>header,getZxy:async()=>undefined})}
  const provider=await createGroundImageryProvider(C,{...layer,coverageBounds:[[125.77,36.92,126.80,37.66],[130.8,37.4,131,37.6]]},new AbortController().signal,dependencies)
  expect(provider.rectangle).toEqual(layer.bounds)
  expect(provider.coversPosition(124.65,37.95)).toBe(false)
  expect(provider.coversPosition(127,37.5)).toBe(false)
  expect(provider.coversPosition(126.3,37.3)).toBe(true)
  expect(provider.coversPosition(130.9,37.48)).toBe(true)
  expect(provider.coversPosition(125.77,36.92)).toBe(true)
  expect(provider.coversPosition(NaN,37)).toBe(false)
  expect(provider.coversPosition(126,Infinity)).toBe(false)
  provider.dispose()
  const legacy=await createGroundImageryProvider(C,layer,new AbortController().signal,dependencies)
  expect(legacy.coversPosition(124.65,37.95)).toBe(true)
  expect(legacy.coversPosition(123,37)).toBe(false)
  legacy.dispose()
  await expect(createGroundImageryProvider(C,{...layer,coverageBounds:[[125,34,126,35]]},new AbortController().signal,
    {canvas,archive:()=>({getHeader:async()=>({...header,minLon:125}),getZxy:async()=>undefined})})).rejects.toThrow('header')
})

test('descriptor strictly validates road-only layer identities and orders landcover below roads', () => {
  expect(validateGroundImagery(descriptor([layer, { ...layer, kind: 'landcover' }])).map(x => x.kind)).toEqual(['landcover', 'roads'])
  for (const change of [ { kind: 'buildings' }, { bounds: [132,33,124,39] }, { minLevel: 13 }, { maxLevel: 20 }, { sha256: 'bad' }, { url: 'file:///roads.pmtiles' }, { url: '//other/roads.pmtiles' }, { surprise: true } ]) {
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

test('range source merges nearby reads from one task and slices each caller its bytes', async () => {
  const file = Uint8Array.from({ length: 300000 }, (_, i) => i % 251), ranges: string[] = []
  const source = groundRangeSource(layer, new AbortController().signal, async (_url, init) => {
    const range = (init!.headers as Record<string,string>).Range!; ranges.push(range)
    const [a, b] = range.slice(6).split('-').map(Number)
    return new Response(file.slice(a!, b! + 1), { status: 206, headers: { 'Content-Range': `bytes ${a}-${b}/${file.length}` } })
  })
  const [x, y, z] = await Promise.all([source.getBytes(100, 50), source.getBytes(1000, 20), source.getBytes(200000, 10)])
  expect(ranges.sort()).toEqual(['bytes=100-1019', 'bytes=200000-200009'])
  expect(new Uint8Array(x.data)).toEqual(file.slice(100, 150)); expect(new Uint8Array(y.data)).toEqual(file.slice(1000, 1020))
  expect(new Uint8Array(z.data)).toEqual(file.slice(200000, 200010))
})

test('range source requires206/exactContentRange and preserves ETag identity', async () => {
  let seen = '', tag = 'one'
  const source = groundRangeSource(layer, new AbortController().signal, async (_url, init) => {
    seen = (init!.headers as Record<string,string>).Range!
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

test('PNG goes see-through only where the vector layer owns the tile', async () => {
  let reads=0
  const owned:number[][]=[]
  const provider = await createGroundImageryProvider(C,layer,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>header,getZxy:async()=>{reads++;return undefined}})},
    (level,west,south,east,north)=>{owned.push([level,west,south,east,north]);return level>=12})
  await provider.requestImage(3492,1586,12);expect(reads).toBe(0)
  await provider.requestImage(218,99,8);expect(reads).toBe(1)
  const [level,west,south,east,north]=owned[0]!
  expect(level).toBe(12);expect(west).toBeLessThan(east);expect(south).toBeLessThan(north);provider.dispose()
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

test('a CDN origin gets 12 slots; same-origin and relative archives keep the local limit', async () => {
  expect(groundParallel('/api/map-data/world-ground/roads.pmtiles',4)).toBe(4)
  expect(groundParallel('https://pub-x.r2.dev/world-ground/roads.pmtiles',4)).toBe(12)
  const provider = await createGroundImageryProvider(C,{...layer,url:'https://pub-x.r2.dev/world-ground/roads.pmtiles'},new AbortController().signal,{canvas,
    archive:()=>({getHeader:async()=>header,getZxy:()=>new Promise(()=>{})})})
  const tasks=Array.from({length:12},()=>provider.requestImage(0,0,0)!)
  expect(tasks.every(Boolean)).toBe(true);expect(provider.requestImage(0,0,0)).toBeUndefined()
  provider.dispose();await Promise.all(tasks.map(task=>expect(task).rejects.toThrow()))
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

test('prebaked palette PNG tiles decode; other colour types do not', async () => {
  let decodes=0
  const open=(colour:number)=>createGroundImageryProvider(C,layer,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:png(colour)})}),decode:async()=>{decodes++;return {width:256,height:256,close(){}}}})
  const palette=await open(3);expect((await palette.requestImage(0,0,0))!.width).toBe(256);expect(decodes).toBe(1);palette.dispose()
  const rgb=await open(2);await expect(rgb.requestImage(0,0,0)!).rejects.toThrow('palette');expect(decodes).toBe(1);rgb.dispose()
})

test('malformed PNG and oversized response do not reach bitmap decoding', async () => {
  let decodes=0
  const provider=await createGroundImageryProvider(C,layer,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:new ArrayBuffer(4)})}),decode:async()=>{decodes++;throw Error('unexpected')}})
  await expect(provider.requestImage(0,0,0)!).rejects.toThrow('RGBA');expect(decodes).toBe(0);provider.dispose()
  const source=groundRangeSource(layer,new AbortController().signal,async()=>new Response(new Uint8Array(5),{status:206,headers:{'Content-Range':'bytes 0-2/3'}}))
  await expect(source.getBytes(0,3)).rejects.toThrow('large')
})

const detailed: GroundImageryLayer = { ...layer, kind: 'landcover', detail: { urlTemplate: '/api/v1/land/ground-imagery/{z}/{x}/{y}.png', maxLevel: 17 } }

test('a prebaked archive carries its detail levels itself (no on-demand detail), up to z19', () => {
  expect(validateGroundImagery(descriptor([{ ...layer, maxLevel: 18 }]))[0]!.maxLevel).toBe(18)
  expect(() => validateGroundImagery(descriptor([{ ...layer, maxLevel: 18, detail: { urlTemplate: '/api/v1/land/road-imagery/{z}/{x}/{y}.png', maxLevel: 17 } }]))).toThrow()
})

test('landcover and roads accept strict zxy detail and archive validation stays at12', async () => {
  expect(validateGroundImagery(descriptor([detailed]))[0]!.detail!.maxLevel).toBe(17)
  for (const bad of [ { ...detailed,maxLevel:11 },
    { ...detailed,detail:{ ...detailed.detail,maxLevel:18 } },
    ...['https://u:p@host/{z}/{x}/{y}.png','/tiles/{z}/{x}/{y}.png?k=secret','/tiles/{z}/{x}/{y}.png#x','/tiles/{s}/{z}/{x}/{y}.png','/tiles/{z}/{y}/{x}.png'].map(urlTemplate=>({ ...detailed,detail:{urlTemplate,maxLevel:17} })) ]) {
    expect(()=>validateGroundImagery(descriptor([bad as GroundImageryLayer]))).toThrow()
  }
  await expect(createGroundImageryProvider(C,detailed,new AbortController().signal,{canvas,archive:()=>({getHeader:async()=>({...header,maxZoom:17}),getZxy:async()=>undefined})})).rejects.toThrow('header')
})

test('z12 only uses PMTiles and z13 only uses bounded detail PNG with shared bitmap lifecycle', async () => {
  const archived: number[] = [], urls: string[] = [];let closed=0
  const provider=await createGroundImageryProvider(C,detailed,new AbortController().signal,{canvas,
    archive:()=>({getHeader:async()=>header,getZxy:async z=>{archived.push(z);return {data:png()}}}),
    get:async url=>{urls.push(url);return new Response(png(),{headers:{'Content-Type':'image/png'}})},
    decode:async()=>({width:256,height:256,close(){closed++}})})
  expect(provider.maximumLevel).toBe(17)
  await provider.requestImage(3492,1587,12);expect(archived).toEqual([12]);expect(urls).toEqual([])
  await provider.requestImage(6985,3174,13);expect(archived).toEqual([12]);expect(urls).toEqual(['/api/v1/land/ground-imagery/13/6985/3174.png'])
  expect(closed).toBe(2);provider.dispose()
})

test('missing or failed detail rejects instead of transparent success replacing a coarse parent', async () => {
  let status=404,decoded=0
  const provider=await createGroundImageryProvider(C,detailed,new AbortController().signal,{canvas,
    archive:()=>({getHeader:async()=>header,getZxy:async()=>({data:png()})}),
    get:async()=>new Response('unavailable',{status}),decode:async()=>{decoded++;return {width:256,height:256,close(){}}}})
  await expect(provider.requestImage(6985,3174,13)!).rejects.toThrow('404')
  status=503;await expect(provider.requestImage(6985,3174,13)!).rejects.toThrow('503')
  expect(decoded).toBe(0)
  expect((await provider.requestImage(3492,1587,12))!.width).toBe(256);expect(decoded).toBe(1)
  provider.dispose()
})

test('detail network work shares4slots and cancellation aborts fetch without decoding a late tile', async () => {
  const pending=deferred<Response>();const signals: AbortSignal[]=[];let decoded=0
  const provider=await createGroundImageryProvider(C,detailed,new AbortController().signal,{canvas,
    archive:()=>({getHeader:async()=>header,getZxy:async()=>undefined}),
    get:async(_url,init)=>{signals.push(init!.signal as AbortSignal);return pending.promise},decode:async()=>{decoded++;throw Error('unexpected')}})
  const tasks=Array.from({length:4},()=>provider.requestImage(6985,3174,13)!)
  expect(provider.requestImage(6985,3174,13)).toBeUndefined();expect(signals.length).toBe(4)
  provider.dispose();expect(signals.every(signal=>signal.aborted)).toBe(true)
  await Promise.all(tasks.map(task=>expect(task).rejects.toThrow()))
  pending.resolve(new Response(png(),{headers:{'Content-Type':'image/png'}}));await Promise.resolve();await Promise.resolve()
  expect(decoded).toBe(0)
})


test('road z14 detail fetches its actual PNG rather than overscaling the z12 archive',async()=>{
 const roads:GroundImageryLayer={...layer,detail:{urlTemplate:'/api/v1/land/road-imagery/{z}/{x}/{y}.png',maxLevel:17}}
 expect(validateGroundImagery(descriptor([roads]))[0]!.detail!.maxLevel).toBe(17)
 const bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAADY0lEQVR4nO3aO1IbQRSGUVHFXglYjwOtFpepGtzACPTo6dd/TuLMjHru1zeQTicAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAANZ1Pv95+/fvc+8HAdpGX3pq9LeBgcLfuAAgLPqSCwACw9+4ACAs+pILAALD37gAICz6kgsAAsN/eXl9b98FACHRl+FvXAAQsu33uAAgZNvvcQFAWPQlFwAEhr9xAUBY9CUXAASGv3EBQFj0JRcATPj1XS0uAAjZ9ntcABCy7fe4ACBk2+9xAUBY9KVhHgRGcl48/M1wDwS9nEOiLw39cNDCOTD8zRQPCbUlR1+a7oHhEcL/bNoHh2uJ/rIlPgSs/GOdIy33gchm299m2Q9GFtv+PhEfkjXZ9o+L+rDMT/R1xX5w5iL8Y8QfAOMS/fEcBsMRfjsOhSGIvg8HRFe+vuvLYdGcbT8Oh0Yztv14HCCHsu3H5iCpTvTzcKhUI/z5OFweIvq5OWjuIvw1OHCuJvr1OHx+Jfx1eQnsEn0GL4RP/Fgni5eDbR/MSwpm2+OFhbHtKXlxAUTPJV7iwoTPb7zMxYieW3ixixA+9/CCJyZ6HuVlT8jXd9TixU/CtucIBmBwtj1HMgwDsu1pxVAMQvT0YEA6Ez49GZQORM8oDE1Dwmc0hudgomdkBukgwmcGBqoi0TMbw1WBH+swK4N2J9ueFRi4G9n2rMTwXcG2Z1WG8ALRk8BAfiF8khhM0RMsekiFT7q4YRU9/BczuL6+g++WHmLbHn625DDb9nCdZQbbtofbTT3goofHTDnswoc6phl60UN9wwcgfDjOkCGIHtoYKgrhQ1vd4xA99NMtFD/Wgf6aRmPbw1iaxGPbw5gOC8m2h/FVDUr0MJcqcQkf5nR3ZKKH+d0cnPBhHVeFJ3pY048R+voO1vYtSNsecnyEadtDnifhQ67nGv+J6CHwAhA+hF0AoofAC0D4EHYBiB7W9h74128ChA9BjvjxDwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApxn9BftZl6TkLkodAAAAAElFTkSuQmCC','base64'),urls:string[]=[];let archives=0,closed=0
 const provider=await createGroundImageryProvider(C,roads,new AbortController().signal,{canvas,
  archive:()=>({getHeader:async()=>header,getZxy:async()=>{archives++;return{data:png()}}}),
  get:async url=>{urls.push(url);return new Response(bytes,{headers:{'Content-Type':'image/png'}})},
  decode:async data=>{expect(Buffer.from(data)).toEqual(bytes);return {width:256,height:256,close(){closed++}}}})
 expect((await provider.requestImage(13976,6335,14))!.width).toBe(256)
 expect(urls).toEqual(['/api/v1/land/road-imagery/14/13976/6335.png']);expect(archives).toBe(0);expect(closed).toBe(1)
 provider.dispose()
})
