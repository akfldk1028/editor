import {expect,test} from 'bun:test'
import {verifyTerrainAnchors,validateTerrainReceipt,terrainOnlySummary} from './verify-ngii-terrain-only'
import {TERRAIN_HEIGHT_CONTRACT} from '../features/world/lib/terrain-height-contract'
const sample=(height:number,zero=false)=>({height,sourceLevels:zero?[-1]:[20],ellipsoidZero:zero,archiveSha256:'a'.repeat(64),contract:TERRAIN_HEIGHT_CONTRACT})
test('independent native gate rejects coast discontinuity without fitted heights',async()=>{
 const p=await verifyTerrainAnchors([{id:'coast',point:[125.1,34.09]}],async()=>sample(12.370484637976),async()=>[10])
 expect(p.passed).toBe(false);expect(p.errors[0]!.error).toBeGreaterThan(.5)
 expect(p.nativeFinite).toBe(1)
})
test('native 0.5m boundary is inclusive; NoData remains classified not accuracy evidence',async()=>{
 const rows=[{id:'a',point:[127,37]},{id:'b',point:[127,38]},{id:'c',point:[127,39]}]
 const p=await verifyTerrainAnchors(rows,async(_lon,lat)=>sample(lat===37?10.5:lat===38?30:0,lat===39),async()=>[10,null,null])
 expect(p.passed).toBe(true);expect(p.nativeFinite).toBe(1);expect(p.nativeNoData).toEqual([{id:'b',classification:'ancestor-supported'},{id:'c',classification:'declared-ellipsoid-zero'}])
 expect(terrainOnlySummary([p],1,3,false).passed).toBe(true)
 expect(terrainOnlySummary([p],1,3,true).passed).toBe(false)
 const empty=await verifyTerrainAnchors([{id:'x',point:[127,37]}],async()=>sample(0,true),async()=>[null])
 expect(terrainOnlySummary([empty],1,1,false).passed).toBe(false)
})
test('invalid native/source policy fails closed',async()=>{
 await expect(verifyTerrainAnchors([{id:'x',point:[127,37]}],async()=>sample(1),async()=>[])).rejects.toThrow('native')
 await expect(verifyTerrainAnchors([{id:'x',point:[127,37]}],async()=>({...sample(1),sourceLevels:[]}),async()=>[1])).rejects.toThrow('policy')
})
test('receipt and archived source pins must agree exactly',()=>{
 const meta={schema:'ngii-heightmap-v1',size:33,archiveZoomOffset:1,grid:'Cesium.GeographicTilingScheme',vrt_sha256:'b'.repeat(64),sourceFilesSHA256:'c'.repeat(64)}
 const receipt={sha256:'a'.repeat(64),vrt_sha256:meta.vrt_sha256,metadata:meta}
 expect(()=>validateTerrainReceipt(meta,receipt,receipt.sha256)).not.toThrow()
 expect(()=>validateTerrainReceipt(meta,{...receipt,vrt_sha256:'d'.repeat(64)},receipt.sha256)).toThrow()
 expect(()=>validateTerrainReceipt(meta,{...receipt,metadata:{...meta,sourceFilesSHA256:'e'.repeat(64)}},receipt.sha256)).toThrow()
})
