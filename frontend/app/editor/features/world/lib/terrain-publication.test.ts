import { expect, test } from 'bun:test'
import { createTerrainPublicationReader } from './terrain-publication'
import { createMapReleaseReader } from './map-release'
import { defaultTerrainArchiveReader } from './terrain-archive'
import { demTerrain } from './terrain'

const sha='a'.repeat(64),vrt='b'.repeat(64)
const release:any={schema:'ace-map-release-v1',releaseId:'c'.repeat(64),buildings:{version:'20261009-2f30a80f',href:'/old'},
  buildingCatalog:{revision:'d'.repeat(64),index:'index.json'},terrain:{url:'https://terrain.test/a.pmtiles',sha256:sha,vrt_sha256:vrt,heightContract:'resolved-ancestor-grid-v1'}}
const metadata={schema:'ngii-heightmap-v1',grid:'Cesium.GeographicTilingScheme',size:33,archiveZoomOffset:1,minLevel:11,maxLevel:12,vrt_sha256:vrt}
const tile=(height:number,level=12)=>({heights:new Float32Array(1089).fill(height),revision:vrt,sourceLevel:level})
function reader(raw:(key:string)=>Promise<any>,change:any={}) {
  return createTerrainPublicationReader(async()=>release, {prepare:async()=>({url:release.terrain.url,archiveSha256:sha,metadata,...change}),raw} as any)
}
class Provider {
  tilingScheme={tileXYToRectangle:(x:number,y:number,z:number)=>{const w=180/2**z;return {west:x*w-180,east:(x+1)*w-180,north:90-y*w,south:90-(y+1)*w}},
    positionToTileXY:(p:any,z:number)=>({x:Math.floor((p.longitude+180)/(180/2**z)),y:Math.floor((90-p.latitude)/(180/2**z))})}
  constructor(public options:any){}
}
const C={CustomHeightmapTerrainProvider:Provider,Math:{toDegrees:(v:number)=>v},Cartographic:{fromDegrees:(longitude:number,latitude:number)=>({longitude,latitude})}}
const provider=(load:ReturnType<typeof createTerrainPublicationReader>)=>demTerrain(C,()=>999,()=>null,()=>{},undefined,async()=>null,()=>{},defaultTerrainArchiveReader,undefined,load)

test('unmarked releases never prepare a new contract, unknown markers reject',async()=>{
  let calls=0
  const old={...release,terrain:{...release.terrain,heightContract:undefined}}
  const load=createTerrainPublicationReader(async()=>old,{prepare:async()=>{calls++;throw Error('unexpected')}} as any)
  expect(await load()).toBeUndefined();expect(calls).toBe(0)
  await expect(createMapReleaseReader(async()=>Response.json({...release,terrain:{...release.terrain,heightContract:'unknown'}}),'/release')()).rejects.toThrow('height contract')
})

test('publication URL, archive identity, VRT and metadata are pinned before raw reads',async()=>{
  for(const change of [{archiveSha256:'f'.repeat(64)},{url:'https://other.test/b.pmtiles'},
    {metadata:{...metadata,vrt_sha256:'f'.repeat(64)}},{metadata:{...metadata,size:17}}]) {
    await expect(reader(async()=>{throw Error('raw must not run')},change)()).rejects.toThrow()
  }
})

test('native NoData uses deterministic ancestors for both displayed and sampled Float32 grids',async()=>{
  const load=reader(async key=>key.startsWith('12/')?tile(NaN):tile(83.125,11))
  const p=provider(load)
  try {
    expect(await p.sampleHeight(127,37)).toBe(83.125)
    const xy=p.tilingScheme.positionToTileXY({longitude:127,latitude:37},12)
    const display=await p.options.callback(xy.x,xy.y,12)
    expect(display).toBeInstanceOf(Float32Array);expect([...display].every(v=>v===83.125)).toBe(true)
    const detail=await p.sampleHeightDetails(127,37)
    expect(detail.sourceLevels).toEqual([11]);expect(detail.ellipsoidZero).toBe(false)
    expect(detail.archiveSha256).toBe(sha)
  }finally{p.dispose()}
})

test('read failure and unavailable raw archive never become cached zero, retry succeeds',async()=>{
  let fail=true
  const p=provider(reader(async()=>{if(fail)throw Error('wire failed');return tile(91)}))
  try {
    await expect(p.sampleHeight(127,37)).rejects.toThrow('wire failed')
    fail=false;expect(await p.sampleHeight(127,37)).toBe(91)
  }finally{p.dispose()}
  const absent=provider(reader(async()=>undefined))
  try{await expect(absent.sampleHeight(127,37)).rejects.toThrow('raw source unavailable')}
  finally{absent.dispose()}
})

test('retired metadata preparation and resolved reads release consumers without waiting for shared work',async()=>{
  let ready!:(value:any)=>void,needed=true
  const p=provider(()=>new Promise(resolve=>{ready=resolve}))
  const sample=p.sampleHeight(127,37,()=>needed).catch((e:Error)=>e.message)
  await new Promise(r=>setTimeout(r,0));needed=false;p.pruneRequests()
  expect(await Promise.race([sample,new Promise(r=>setTimeout(()=>r('blocked'),100))])).toBe('terrain sample retired')
  p.dispose();ready(undefined)
  let finish!:(value:any)=>void,neededRaw=true
  const load=reader(async key=>key==='12/6985/1206'?new Promise(resolve=>{finish=resolve}):tile(72,Number(key.split('/')[0])))
  const q=provider(load)
  const old=q.sampleHeight(127,37,()=>neededRaw).catch((e:Error)=>e.message)
  await new Promise(r=>setTimeout(r,0));neededRaw=false;q.pruneRequests()
  try {
    expect(await Promise.race([old,new Promise(r=>setTimeout(()=>r('blocked'),100))])).toBe('terrain sample retired')
    expect(await q.sampleHeight(128,37)).toBe(72)
  }finally{q.dispose();finish?.(tile(90))}
})

test('custom archive retains legacy behavior and never calls publication loader',async()=>{
  let calls=0
  const p=demTerrain(C,()=>0,()=>null,()=>{},undefined,async()=>null,()=>{},async()=>tile(45,20),undefined,async()=>{calls++;throw Error('unexpected')})
  try{expect(await p.sampleHeight(127,37)).toBe(45);expect(calls).toBe(0)}finally{p.dispose()}
})

test('exact boundary contributors and camera order match the baker contract',async()=>{
  const raw=async(key:string)=>{
    if(key.startsWith('11/'))return tile(20,11)
    const value=tile(NaN);value.heights[0]=10;return value
  }
  const load=reader(raw),contract=(await load())!,p=provider(load)
  const width=180/2**12,x=6985,y=1206,lon=x*width-180,lat=90-y*width
  try {
    const display=await p.options.callback(x,y,12)
    expect(display[0]).toBe(10);expect(display[1]).toBe(20)
    expect(await p.sampleHeightDetails(lon,lat)).toEqual(await contract.samplePosition(lon,lat))
    expect((await p.sampleHeightDetails(lon,lat)).sourceLevels).toEqual([12])
    const offset=width/64
    expect(await p.sampleHeightDetails(lon+offset,lat-offset)).toEqual(await contract.samplePosition(lon+offset,lat-offset))
  }finally{p.dispose()}
})
