import type { MapRelease } from './map-release'
import { expect, test } from 'bun:test'
import { BuildingCatalog, type BuildingRegion, type CatalogView } from './building-catalog'

const revision='a'.repeat(64)
const region=(id:string):BuildingRegion=>({id,z:14,x:1,y:1,bounds:[127,37,128,38],url:`/world-buildings/${id}/tileset.json`,footprints:`/world-buildings/${id}/footprints.json`,coverage:[],partialCoverage:['16/4/4']})
const view=(lon:number):CatalogView=>({box:[lon-.1,37,lon+.1,38],focus:{lon,lat:37.5}})
const index={schema:'world-buildings/catalog-index-v1',revision,shards:[{key:'a',bounds:[127,37,128,38],href:'a.json'},{key:'b',bounds:[129,37,130,38],href:'b.json'}]}

test('default fetch is invoked without binding it to the catalog instance',async()=>{
  const original=globalThis.fetch
  globalThis.fetch=(async function(this:unknown,url:any){
    if(this instanceof BuildingCatalog)throw new TypeError('Illegal invocation')
    if(String(url).endsWith('latest.json'))return Response.json({revision,index:'index.json'})
    if(String(url).endsWith('index.json'))return Response.json(index)
    return Response.json({schema:'world-buildings/shard-v1',revision,regions:[region('a')]})
  }) as typeof fetch
  try {
    const seen:BuildingRegion[][]=[]
    await new BuildingCatalog().read(()=>view(127.5),rows=>seen.push(rows),new AbortController().signal)
    expect(seen[0]![0]!.id).toBe('a')
  } finally {globalThis.fetch=original}
})

test('travel reads the new nearby shard immediately without a full catalog or root refresh',async()=>{
  const calls:string[]=[]
  const reader=new BuildingCatalog(async url=>{
    calls.push(url)
    if(url.endsWith('latest.json'))return Response.json({revision,index:'index.json'})
    if(url.endsWith('index.json'))return Response.json(index)
    return Response.json({schema:'world-buildings/shard-v1',revision,regions:[region(url.endsWith('a.json')?'a':'b')]})
  })
  const rows:BuildingRegion[][]=[];const signal=new AbortController().signal
  await reader.read(()=>view(127.5),r=>rows.push(r),signal)
  expect(reader.needsView(view(129.5))).toBe(true)
  await reader.read(()=>view(129.5),r=>rows.push(r),signal)
  expect(calls.filter(s=>s.endsWith('latest.json'))).toHaveLength(1)
  expect(calls.some(s=>s.endsWith('/catalog.json'))).toBe(false)
  expect(rows[0]![0]!.coverage).toEqual([]);expect(rows.at(-1)![0]!.id).toBe('b')
  // Cached data must be re-applied after a different shard replaced the candidates.
  expect(reader.needsView(view(127.5))).toBe(true)
  const before=calls.length
  await reader.read(()=>view(127.5),r=>rows.push(r),signal)
  expect(rows.at(-1)![0]!.id).toBe('a')
  expect(calls.length).toBe(before)
  expect(reader.needsView(view(127.5))).toBe(false)
})

test('a failed shard is retried after cooldown and cannot create a tight request loop',async()=>{
  let time=0,shards=0
  const reader=new BuildingCatalog(async url=>{
    if(url.endsWith('latest.json'))return Response.json({revision,index:'index.json'})
    if(url.endsWith('index.json'))return Response.json(index)
    shards++;return new Response('',{status:503})
  },()=>time)
  await reader.read(()=>view(127.5),()=>{},new AbortController().signal)
  expect(shards).toBe(1);expect(reader.needsView(view(127.5))).toBe(false)
  time=5001;expect(reader.needsView(view(127.5))).toBe(true)
})

test('a farther shard completing first cannot publish geometry before the nearer shard',async()=>{
  let release:()=>void=()=>{}
  const nearer=new Promise<void>(resolve=>{release=resolve}),seen:string[]=[]
  const reader=new BuildingCatalog(async url=>{
    if(url.endsWith('latest.json'))return Response.json({revision,index:'index.json'})
    if(url.endsWith('index.json'))return Response.json(index)
    if(url.endsWith('a.json'))await nearer
    return Response.json({schema:'world-buildings/shard-v1',revision,regions:[region(url.endsWith('a.json')?'a':'b')]})
  })
  const job=reader.read(()=>({box:[127,37,130,38],focus:{lon:127.5,lat:37.5}}),rows=>seen.push(rows.map(r=>r.id).join(',')),new AbortController().signal)
  await new Promise(r=>setTimeout(r,10));expect(seen).toEqual([])
  release();await job;expect(seen).toEqual(['a','a,b'])
})

test('national release refuses legacy catalog before fallback/index requests', async () => {
  let calls = 0
  const catalog = new BuildingCatalog(async () => { calls++; return Response.json({}) }, Date.now,
    async () => ({ schema: 'ace-map-release-v2' }) as MapRelease)
  await expect(catalog.read(() => view(127), () => {}, new AbortController().signal)).rejects.toThrow('no legacy')
  expect(calls).toBe(0)
})
