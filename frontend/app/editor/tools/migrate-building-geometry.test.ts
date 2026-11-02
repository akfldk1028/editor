import { test, expect } from 'bun:test'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { migrateBuildingGeometry } from './migrate-building-geometry'
import { BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import type { Footprint } from '../features/world/lib/building-geometry'

async function setup() {
  const root=await mkdtemp(join(tmpdir(),'geometry-migration-'))
  const f:Footprint={key:'16/55906/25340/1',pnu:'kept',ring:[[127.105,37.732],[127.106,37.732],[127.106,37.733],[127.105,37.733],[127.105,37.732]],z:68.9123456789,h:10,s:'m'}
  const region={id:'old',z:14,x:13976,y:6335,bounds:[127,37,128,38],coverage:['16/55906/25340'],partialCoverage:['16/55907/25340'],
    url:'/world-buildings/old/tileset.json',footprints:'/world-buildings/old/footprints.json',groundPolicy:'local-dem',groundRevision:'ground-one',groundSource:'/world-buildings/old/ground-source.json',counts:{measured:1,estimated:0,unknown:0}}
  await mkdir(join(root,'old'))
  await writeFile(join(root,'old','footprints.json'),JSON.stringify([f]))
  const ground='{ "fileSignature": "ground-one", "evidence": "exact bytes" }'
  await writeFile(join(root,'old','ground-source.json'),ground)
  await writeFile(join(root,'catalog.json'),JSON.stringify({version:1,source:'archive/version/buildings.pmtiles',regions:[region]}))
  const hole=[[127.1052,37.7322],[127.1058,37.7322],[127.1058,37.7328],[127.1052,37.7328],[127.1052,37.7322]]
  const options={catalogRoot:root,assetRoot:root,regionKeys:new Set(['14/13976/6335']),limit:16,resume:true,minFreeBytes:0,
    decodeRegion:async()=>[{...f,z:1,h:999,holes:[hole]}]}
  return {root,f,region,ground,hole,options}
}

test('bounded migration preserves ground bytes, component identity and coverage while writing immutable v3 tiles', async()=>{
  const s=await setup()
  try {
    const report=await migrateBuildingGeometry(s.options)
    expect(report.migrated).toBe(1)
    const catalog=JSON.parse(await readFile(join(s.root,'catalog.json'),'utf8')),next=catalog.regions[0]
    expect(next.id).not.toBe('old');expect(next.meshRevision).toBe(BUILDING_MESH_REVISION)
    expect(next.coverage).toEqual(s.region.coverage);expect(next.partialCoverage).toEqual(s.region.partialCoverage)
    expect(next.groundRevision).toBe('ground-one')
    expect(await readFile(join(s.root,next.id,'ground-source.json'),'utf8')).toBe(s.ground)
    const [f]=JSON.parse(await readFile(join(s.root,next.id,'footprints.json'),'utf8'))
    expect(f).toEqual({...s.f,holes:[s.hole]})
    expect(JSON.parse(await readFile(join(s.root,'old','footprints.json'),'utf8'))).toEqual([s.f])
    const tree=JSON.parse(await readFile(join(s.root,next.id,'tileset.json'),'utf8'))
    expect(tree.root.refine).toBe('REPLACE');expect(tree.root.children[0].children[0].geometricError).toBe(0)
    const receipt=JSON.parse(await readFile(join(s.root,next.id,'geometry-migration.json'),'utf8'))
    expect(receipt.beforeIdentitySHA256).toBe(receipt.afterIdentitySHA256)
    let reads=0
    const resumed=await migrateBuildingGeometry({...s.options,decodeRegion:async()=>{reads++;return[]}})
    expect(resumed.skipped).toBe(1);expect(reads).toBe(0)
    expect(JSON.parse(await readFile(join(s.root,'catalog.json'),'utf8')).regions[0].id).toBe(next.id)
  } finally {await rm(s.root,{recursive:true})}
})

test('missing source and insufficient disk leave catalog and originals unchanged',async()=>{
  const s=await setup()
  try {
    const before=await readFile(join(s.root,'catalog.json'),'utf8')
    await expect(migrateBuildingGeometry({...s.options,decodeRegion:async()=>[]})).rejects.toThrow('Missing decoded')
    expect(await readFile(join(s.root,'catalog.json'),'utf8')).toBe(before)
    await expect(migrateBuildingGeometry({...s.options,minFreeBytes:Number.MAX_SAFE_INTEGER})).rejects.toThrow('reserve')
    expect(await readFile(join(s.root,'catalog.json'),'utf8')).toBe(before)
  } finally {await rm(s.root,{recursive:true})}
})

test('resume refuses a corrupted v3 binary instead of silently declaring success',async()=>{
  const s=await setup()
  try {
    await migrateBuildingGeometry(s.options)
    const row=JSON.parse(await readFile(join(s.root,'catalog.json'),'utf8')).regions[0]
    await writeFile(join(s.root,row.id,'14-13976-6335.b3dm'),'broken')
    await expect(migrateBuildingGeometry(s.options)).rejects.toThrow('Incomplete v3')
  } finally {await rm(s.root,{recursive:true})}
})

test('selection must be explicit, bounded, and refer to existing unique regions',async()=>{
  const s=await setup()
  try {
    await expect(migrateBuildingGeometry({...s.options,regionKeys:new Set()})).rejects.toThrow('bounded')
    await expect(migrateBuildingGeometry({...s.options,regionKeys:new Set(['14/0/0'])})).rejects.toThrow('Missing selected')
    await expect(migrateBuildingGeometry({...s.options,limit:0})).rejects.toThrow('limit')
  } finally {await rm(s.root,{recursive:true})}
})

test('a concurrent catalog edit cannot be overwritten by a geometry candidate',async()=>{
  const s=await setup()
  try {
    const concurrent=JSON.stringify({version:1,source:'archive/version/buildings.pmtiles',regions:[s.region],externalRevision:'changed'})
    await expect(migrateBuildingGeometry({...s.options,decodeRegion:async()=>{
      await writeFile(join(s.root,'catalog.json'),concurrent)
      return [s.f]
    }})).rejects.toThrow('Catalog changed')
    expect(await readFile(join(s.root,'catalog.json'),'utf8')).toBe(concurrent)
  } finally {await rm(s.root,{recursive:true})}
})

test('resume checks body hashes and requires its migration receipt',async()=>{
  const s=await setup()
  try {
    await migrateBuildingGeometry(s.options)
    const row=JSON.parse(await readFile(join(s.root,'catalog.json'),'utf8')).regions[0]
    const path=join(s.root,row.id,'14-13976-6335.b3dm'),bytes=await readFile(path),corrupt=Buffer.from(bytes)
    corrupt[corrupt.length-1]^=1
    await writeFile(path,corrupt)
    await expect(migrateBuildingGeometry(s.options)).rejects.toThrow('checksum')
    await writeFile(path,bytes)
    await rm(join(s.root,row.id,'geometry-migration.json'))
    await expect(migrateBuildingGeometry(s.options)).rejects.toThrow()
  } finally {await rm(s.root,{recursive:true})}
})

test('region limit advances incrementally and resume leaves completed regions immutable',async()=>{
  const s=await setup()
  try {
    const other={...s.region,id:'other',x:s.region.x+1,coverage:['16/55908/25340'],partialCoverage:[],groundSource:'/world-buildings/other/ground-source.json'}
    const f2={...s.f,key:'16/55908/25340/1'}
    await mkdir(join(s.root,'other'))
    await writeFile(join(s.root,'other','footprints.json'),JSON.stringify([f2]))
    await writeFile(join(s.root,'other','ground-source.json'),s.ground)
    await writeFile(join(s.root,'catalog.json'),JSON.stringify({source:'archive/version/buildings.pmtiles',regions:[s.region,other]}))
    const options={...s.options,regionKeys:new Set(['14/13976/6335','14/13977/6335']),limit:1,decodeRegion:async(x:number)=>[x===s.region.x?s.f:f2]}
    const first=await migrateBuildingGeometry(options)
    expect(first.migrated).toBe(1);expect(first.remaining).toBe(1)
    const rows=JSON.parse(await readFile(join(s.root,'catalog.json'),'utf8')).regions
    expect(rows[1].id).toBe('other')
    const second=await migrateBuildingGeometry(options)
    expect(second.skipped).toBe(1);expect(second.migrated).toBe(1);expect(second.remaining).toBe(0)
    const final=JSON.parse(await readFile(join(s.root,'catalog.json'),'utf8')).regions
    expect(final[0].id).toBe(rows[0].id);expect(final[1].id).not.toBe('other')
  } finally {await rm(s.root,{recursive:true})}
})
