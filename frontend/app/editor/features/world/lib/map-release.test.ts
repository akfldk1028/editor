import { test, expect } from 'bun:test'
import { createMapReleaseReader } from './map-release'

const release = { schema:'ace-map-release-v1', releaseId:'a'.repeat(64), buildings:{version:'20261009-2f30a80f',href:'/api/map-data/buildings/20261009-2f30a80f/buildings.pmtiles'},
  buildingCatalog:{revision:'b'.repeat(64),index:'catalogs/index.json'},terrain:{url:'/api/map-data/world-terrain/a.pmtiles',vrt_sha256:'c'.repeat(64),sha256:'d'.repeat(64)} }

test('independent loaders share and pin one release across a server update',async()=>{
  let calls=0
  const read=createMapReleaseReader(async()=>{calls++;return Response.json({...release,releaseId:(calls===1?'a':'f').repeat(64)})},'/release')
  const [a,b]=await Promise.all([read(),read()])
  expect(a).toBe(b);expect((await read())?.releaseId).toBe('a'.repeat(64));expect(calls).toBe(1)
})

test('missing release permits old local installs; invalid or transient release never silently mixes datasets',async()=>{
  expect(await createMapReleaseReader(async()=>new Response(null,{status:404}),'/release')()).toBeUndefined()
  let calls=0
  const read=createMapReleaseReader(async()=>++calls===1?new Response(null,{status:503}):Response.json(release),'/release')
  await expect(read()).rejects.toThrow('503');expect((await read())?.releaseId).toBe(release.releaseId)
  await expect(createMapReleaseReader(async()=>Response.json({}),'/release')()).rejects.toThrow('Invalid map release')
})


const nationalRelease = () => {
  const coverage = { schema:'ngii-national-coverage-v1', sourcePlanSHA256:'a'.repeat(64), catalogRevision:'b'.repeat(64),
    regionCount:17, buildings:17, components:17, supportedGroundBuildings:16, unresolvedGroundBuildings:1, unclassifiedProvinceBuildings:0,
    missingRegions:0, partialRegions:0, runtimeValidated:false,
    provinces:['11','26','27','28','29','30','31','36','41','43','44','46','47','48','50','51','52'] }
  return { schema:'ace-map-release-v2', releaseId:'f'.repeat(64),sourceFamily:'NGII-B021',runtimeValidationRequired:true,
    terrain:{...release.terrain,heightContract:'resolved-ancestor-grid-v1'},coverage,
    nationalBuildings:{schema:'world-buildings/national-v1',url:'/api/map-data/world-buildings/national/version/tileset.json',
      sourceSha256:coverage.sourcePlanSHA256,terrainVrtSha256:release.terrain.vrt_sha256,catalogRevision:coverage.catalogRevision,
      coverageSha256:new Bun.CryptoHasher('sha256').update(JSON.stringify(coverage,Object.keys(coverage).sort())).digest('hex'),
      materialRevision:'neutral-opaque-v1',hierarchy:'replace-coarse-ancestors-v1',
      coverage:{expectedRegions:17,completeRegions:17,missingRegions:0,partialRegions:0}} }
}
test('v2 pins publisher fields and verifies coverage SHA without legacy PMTiles fields', async () => {
  const value=nationalRelease()
  const result=await createMapReleaseReader(async()=>Response.json(value),'/release')()
  expect(result?.schema).toBe('ace-map-release-v2')
  expect(result).not.toHaveProperty('buildings')
  for (const alter of [
    (r:ReturnType<typeof nationalRelease>)=>{r.coverage.provinces.pop()},
    (r:ReturnType<typeof nationalRelease>)=>{r.nationalBuildings.coverageSha256='e'.repeat(64)},
    (r:ReturnType<typeof nationalRelease>)=>{r.terrain.heightContract='legacy'},
    (r:ReturnType<typeof nationalRelease>)=>{r.coverage.partialRegions=1},
  ]) {
    const changed=nationalRelease();alter(changed)
    await expect(createMapReleaseReader(async()=>Response.json(changed),'/release')()).rejects.toThrow()
  }
})
