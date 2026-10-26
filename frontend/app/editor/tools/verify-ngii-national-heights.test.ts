import { expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { canonicalJSON, reusableProof, verifyRegion } from './verify-ngii-national-heights'
import { createTerrainHeightContract } from '../features/world/lib/terrain-height-contract'
import type { CanonicalBuilding } from './ngii-mesh-input'
const sha='a'.repeat(64),id='ngii:'+sha
const row:CanonicalBuilding={canonicalBuildingId:id,sourceUFID:'source',anchorWGS84:[0,0],geomWGS84:{type:'MultiPolygon',coordinates:[[[[0,0],[.01,0],[0,.01],[0,0]]],[[[.02,0],[.03,0],[.02,.01],[.02,0]]]]},h:3.4,heightSource:{kind:'source-floors',floors:1},provenance:{family:'NGII-B021',productCode:'B021',productKind:'continuous-topographic',layer:'N3A_B0010000',edition:'2024',sourceManifestSHA256:sha,productReceiptSHA256:sha,row:3}}
async function fixture(noData=false){const contract=createTerrainHeightContract(async()=>noData?null:new Float32Array(33*33).fill(60),{archiveSha256:sha,minLevel:0,maxLevel:1});const ground=await contract.samplePosition(0,0);return {sample:contract.samplePosition,grounds:[{id,sourceUFID:row.sourceUFID,ground,provenance:row.provenance,heightSource:row.heightSource}],footprints:[{key:id+'/0',z:ground.height},{key:id+'/1',z:ground.height}]}}
test('independent canonical-anchor sampling checks every multipart component and native finite datum',async()=>{
 const f=await fixture();let points:number[][]=[];const p=await verifyRegion('14/1/2',[row],f.grounds,f.footprints,f.sample,async input=>{points=input;return [60.2]})
 expect(points).toEqual([[0,0]]);expect(p.components).toBe(2);expect(p.datumMaximum).toBe(0);expect(p.displayMaximum).toBeCloseTo(.2);expect(p.passed).toBe(true)
 expect(p.inputSHA256).toBe(createHash('sha256').update(JSON.stringify(row)+'\n').digest('hex'))
})
test('native NoData remains explicitly classified rather than zero or a native accuracy pass',async()=>{
 for(const zero of [false,true]){const f=await fixture(zero),p=await verifyRegion('14/1/2',[row],f.grounds,f.footprints,f.sample,async()=>[null]);expect(p.nativeFinite).toBe(0);expect(p.displayMaximum).toBeNull();expect(p.nativeEvidence).toBe('insufficient');expect(p.nativeNoData).toEqual([{key:id,classification:zero?'declared-ellipsoid-zero':'ancestor-supported'}]);expect(p.unresolvedGroundBuildings).toBe(zero?1:0)}
})
test('threshold failures are evidence, never silently accepted or relaxed',async()=>{
 const f=await fixture();f.footprints[1]!.z+=.011
 const p=await verifyRegion('14/1/2',[row],f.grounds,f.footprints,f.sample,async()=>[60.501]);expect(p.passed).toBe(false);expect(p.errors.map(e=>e.kind)).toEqual(['component-datum','native-display'])
})
test('missing, duplicate, extra, provenance mismatch and non-finite worker values fail closed',async()=>{
 const f=await fixture()
 await expect(verifyRegion('r',[row],f.grounds,f.footprints.slice(0,1),f.sample,async()=>[60])).rejects.toThrow('Missing canonical component')
 await expect(verifyRegion('r',[row],f.grounds,[...f.footprints,f.footprints[0]!],f.sample,async()=>[60])).rejects.toThrow('Duplicate')
 await expect(verifyRegion('r',[row],f.grounds,[...f.footprints,{key:id+'/2',z:60}],f.sample,async()=>[60])).rejects.toThrow('Extra')
 await expect(verifyRegion('r',[row],f.grounds,f.footprints,f.sample,async()=>[])).rejects.toThrow('native response')
 await expect(verifyRegion('r',[row],f.grounds,f.footprints,f.sample,async()=>[NaN])).rejects.toThrow('native response')
 f.grounds[0]!.provenance={...row.provenance,row:999}
 await expect(verifyRegion('r',[row],f.grounds,f.footprints,f.sample,async()=>[60])).rejects.toThrow('provenance')
})
test('resumed evidence is bound to exact run, candidate receipt and proof bytes',async()=>{
 const f=await fixture(),proof=await verifyRegion('r',[row],f.grounds,f.footprints,f.sample,async()=>[60]);const value={runSHA256:'run',receiptSHA256:'receipt',proofSHA256:createHash('sha256').update(canonicalJSON(proof)).digest('hex'),proof}
 expect(reusableProof(value,'run','receipt')).toEqual(proof)
 expect(()=>reusableProof(value,'other','receipt')).toThrow('mismatch')
 expect(()=>reusableProof(value,'run','other')).toThrow('mismatch')
 value.proof.components++
 expect(()=>reusableProof(value,'run','receipt')).toThrow('mismatch')
})

test('completed inventory pin rejects changed snapshot, inventory bytes and duplicate owners without recounting the nationwide database', async () => {
  const {validateCompletedInventoryPin}=await import('./verify-ngii-national-heights')
  const plan={schema:'ngii-canonical-plan-v1',storageSchema:'canonical-sqlite-v2',planSHA256:sha,expectedRows:1,sources:[{id:'source',expectedRows:1,manifest:row.provenance}]}
  const inventory={schema:'ngii-canonical-regions-v1',planSHA256:sha,sourceComplete:true,sourceRows:1,buildingCount:1,regionCount:1,regions:[{region14:'14/1/2',buildings:1,components:2}]}
  const binding={snapshotSHA256:sha,regionsSHA256:'b'.repeat(64)}
  expect(()=>validateCompletedInventoryPin({...binding},binding,plan,inventory)).not.toThrow()
  expect(()=>validateCompletedInventoryPin({...binding,snapshotSHA256:'c'.repeat(64)},binding,plan,inventory)).toThrow('pin mismatch')
  expect(()=>validateCompletedInventoryPin({...binding,regionsSHA256:'c'.repeat(64)},binding,plan,inventory)).toThrow('pin mismatch')
  expect(()=>validateCompletedInventoryPin(binding,binding,plan,{...inventory,sourceComplete:false})).toThrow('inventory')
  expect(()=>validateCompletedInventoryPin(binding,binding,plan,{...inventory,regionCount:2,buildingCount:2,regions:[...inventory.regions,...inventory.regions]})).toThrow('inventory')
})

test('watch summary stays incomplete for pending regions, STOP, native-empty and quality failure',async()=>{
 const {verificationProgress}=await import('./verify-ngii-national-heights')
 const ok={components:2,passed:true,nativeFinite:1}
 expect(verificationProgress([],2,4,false)).toMatchObject({complete:false,passed:false,pendingRegions:2})
 expect(verificationProgress([ok],2,4,false)).toMatchObject({complete:false,passed:false,pendingRegions:1})
 expect(verificationProgress([ok,ok],2,4,false)).toMatchObject({complete:true,passed:true,pendingRegions:0})
 expect(verificationProgress([ok,ok],2,4,false,true).complete).toBe(false)
 expect(verificationProgress([ok,ok],2,4,true).complete).toBe(false)
 expect(verificationProgress([{...ok,nativeFinite:0}],1,2,false).passed).toBe(false)
 expect(verificationProgress([{...ok,passed:false}],1,2,false).passed).toBe(false)
 expect(()=>verificationProgress([ok,ok],1,2,false)).toThrow('exceeds')
})

test('watch discovers only atomically complete regions and refuses invalid or duplicate completed candidates',async()=>{
 const {discoverCompletedCandidates}=await import('./verify-ngii-national-heights')
 const {mkdtemp,mkdir,writeFile,rename,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path')
 const root=await mkdtemp(join(tmpdir(),'height-watch-')),found=new Map<string,string>(),wanted=new Set(['14/1/2'])
 try{
  await mkdir(join(root,'.staging'));await discoverCompletedCandidates(root,wanted,found);expect(found.size).toBe(0)
  const staged=join(root,'.staging','candidate');await mkdir(staged);await writeFile(join(staged,'candidate-receipt.json'),JSON.stringify({owner:'14/1/2',completeRegion:true}))
  await discoverCompletedCandidates(root,wanted,found);expect(found.size).toBe(0)
  await rename(staged,join(root,'14-1-2-'+'a'.repeat(16)));await discoverCompletedCandidates(root,wanted,found);expect(found.size).toBe(1)
  await discoverCompletedCandidates(root,wanted,found);expect(found.size).toBe(1)
  const duplicate=join(root,'14-1-2-'+'b'.repeat(16));await mkdir(duplicate);await writeFile(join(duplicate,'candidate-receipt.json'),'{}')
  await expect(discoverCompletedCandidates(root,wanted,found)).rejects.toThrow('Duplicate')
  await rm(duplicate,{recursive:true});await writeFile(join(found.get('14/1/2')!,'candidate-receipt.json'),JSON.stringify({owner:'14/1/2',completeRegion:false}))
  await expect(discoverCompletedCandidates(root,wanted,new Map())).rejects.toThrow('Invalid completed')
 }finally{await rm(root,{recursive:true,force:true})}
})
