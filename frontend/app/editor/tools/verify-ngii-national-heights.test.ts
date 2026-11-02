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
test('served-terrain datum failures block; native disagreement is recorded only',async()=>{
 const f=await fixture();f.footprints[1]!.z+=.011
 const p=await verifyRegion('14/1/2',[row],f.grounds,f.footprints,f.sample,async()=>[60.501]);expect(p.passed).toBe(false);expect(p.errors.map(e=>e.kind)).toEqual(['component-datum']);expect(p.nativeOver).toBe(1)
})
test('native DEM disagreement above 0.5 m is recorded per region without failing the region',async()=>{
 const f=await fixture(),p=await verifyRegion('14/1/2',[row],f.grounds,f.footprints,f.sample,async()=>[62.37])
 expect(p.passed).toBe(true);expect(p.errors).toEqual([]);expect(p.nativeEvidence).toBe('recorded');expect(p.nativeOver).toBe(1);expect(p.displayMaximum).toBeCloseTo(2.37)
 const q=await verifyRegion('14/1/2',[row],f.grounds,f.footprints,f.sample,async()=>[60.4]);expect(q.nativeOver).toBe(0);expect(q.nativeEvidence).toBe('recorded')
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

test('merge reuses a shard-verified region only while receipt payload stamps are unchanged',async()=>{
 const {candidateFileStamps,stampedReuse}=await import('./verify-ngii-national-heights')
 const {mkdtemp,writeFile,utimes,rm,rename}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path')
 const root=await mkdtemp(join(tmpdir(),'height-stamp-')),receipt={files:[{path:'a.b3dm.gz'},{path:'footprints.json.gz'}]}
 try{
  await writeFile(join(root,'a.b3dm.gz'),'aaaa');await writeFile(join(root,'footprints.json.gz'),'ffff')
  const old=new Date('2026-01-01T00:00:00Z');for(const f of receipt.files)await utimes(join(root,f.path),old,old)
  const stamps=await candidateFileStamps(root,receipt),previous={runSHA256:'run',receiptSHA256:'receipt',fileStamps:stamps}
  expect(stampedReuse(previous,'run','receipt',await candidateFileStamps(root,receipt))).toBe(true)
  expect(stampedReuse(previous,'other','receipt',stamps)).toBe(false)
  expect(stampedReuse(previous,'run','other',stamps)).toBe(false)
  expect(stampedReuse({runSHA256:'run',receiptSHA256:'receipt'},'run','receipt',stamps)).toBe(false)
  expect(stampedReuse({...previous,fileStamps:[]},'run','receipt',[])).toBe(false)
  // same size, modified bytes: mtime changes, full re-hash required
  await writeFile(join(root,'a.b3dm.gz'),'bbbb');expect(stampedReuse(previous,'run','receipt',await candidateFileStamps(root,receipt))).toBe(false)
  // restoring the old mtime still fails if the file was replaced (inode) or resized
  await writeFile(join(root,'x'),'cccc');await rename(join(root,'x'),join(root,'a.b3dm.gz'));await utimes(join(root,'a.b3dm.gz'),old,old)
  const replaced=await candidateFileStamps(root,receipt);expect(replaced[0]!.mtimeNs).toBe(stamps[0]!.mtimeNs);expect(stampedReuse(previous,'run','receipt',replaced)).toBe(false)
  await writeFile(join(root,'footprints.json.gz'),'fffff');await utimes(join(root,'footprints.json.gz'),old,old)
  expect(stampedReuse({...previous,fileStamps:replaced},'run','receipt',await candidateFileStamps(root,receipt))).toBe(false)
  await expect(candidateFileStamps(root,{files:[{path:'../x'}]})).rejects.toThrow('path')
  await expect(candidateFileStamps(root,{files:[]})).rejects.toThrow('receipt')
 }finally{await rm(root,{recursive:true,force:true})}
})

test('shards and merge exclude each other; stale dead-pid locks are removed',async()=>{
 const {acquireVerificationLock,SHARD_LOCK}=await import('./verify-ngii-national-heights')
 const {mkdtemp,writeFile,rm,unlink,stat}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path'),{spawnSync}=await import('node:child_process')
 const root=await mkdtemp(join(tmpdir(),'height-lock-')),dead=spawnSync(process.execPath,['-e','0']).pid!
 try{
  expect(SHARD_LOCK.test('verification-shard-1.lock')).toBe(true);expect(SHARD_LOCK.test('verification-shard-1-of-5.lock')).toBe(true);expect(SHARD_LOCK.test('verification.lock')).toBe(false)
  const shard=await acquireVerificationLock(root,'-shard-1-of-5')
  await expect(acquireVerificationLock(root,'-shard-1-of-5')).rejects.toThrow('live')
  await expect(acquireVerificationLock(root,'')).rejects.toThrow('shard lock')
  await expect(stat(join(root,'verification.lock'))).rejects.toThrow()
  const other=await acquireVerificationLock(root,'-shard-2-of-5');await unlink(other);await unlink(shard)
  await writeFile(join(root,'verification-shard-3.lock'),String(process.pid))
  await expect(acquireVerificationLock(root,'')).rejects.toThrow('shard lock');await unlink(join(root,'verification-shard-3.lock'))
  const merge=await acquireVerificationLock(root,'')
  await expect(acquireVerificationLock(root,'-shard-0-of-5')).rejects.toThrow('merge lock');await unlink(merge)
  await writeFile(join(root,'verification.lock'),String(dead));expect(await acquireVerificationLock(root,'')).toBe(join(root,'verification.lock'));await unlink(join(root,'verification.lock'))
  await writeFile(join(root,'verification-shard-4-of-5.lock'),String(dead));await acquireVerificationLock(root,'');await expect(stat(join(root,'verification-shard-4-of-5.lock'))).rejects.toThrow()
  await unlink(join(root,'verification.lock'));await writeFile(join(root,'verification.lock'),'')
  await expect(acquireVerificationLock(root,'')).rejects.toThrow('live')
 }finally{await rm(root,{recursive:true,force:true})}
})

test('verification input pin is written atomically once and readers retry partial JSON',async()=>{
 const {pinVerificationInputs}=await import('./verify-ngii-national-heights')
 const {mkdtemp,writeFile,readFile,readdir,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path')
 const root=await mkdtemp(join(tmpdir(),'height-pin-')),pin=join(root,'verification-inputs.json'),identity={schema:'s',b:1,a:[1,2]}
 try{
  await Promise.all(Array.from({length:8},()=>pinVerificationInputs(pin,identity)))
  expect(JSON.parse(await readFile(pin,'utf8'))).toEqual(identity);expect(await readdir(root)).toEqual(['verification-inputs.json'])
  await pinVerificationInputs(pin,{a:[1,2],b:1,schema:'s'})
  await expect(pinVerificationInputs(pin,{...identity,b:2})).rejects.toThrow('identity changed')
  await writeFile(pin,'{"schema":');setTimeout(()=>writeFile(pin,JSON.stringify(identity)),120)
  await pinVerificationInputs(pin,identity)
  await writeFile(pin,'{"schema":');await expect(pinVerificationInputs(pin,identity,2)).rejects.toThrow('unreadable')
 }finally{await rm(root,{recursive:true,force:true})}
})
