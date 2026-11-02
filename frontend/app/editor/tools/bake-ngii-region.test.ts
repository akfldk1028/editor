import { gunzipSync } from 'node:zlib'
import { expect, test } from 'bun:test'
import { mkdtemp, writeFile, rm, readFile, stat, mkdir, rename } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { parseReserveGiB, shardRegions, bindCandidateInputs, selectRegions, verifyExistingCandidate, main, createRegionMeshWriter, NGII_ASSET_PACKING, encodeCandidatePayload, createCandidateStage, renameCandidateAtomically } from './bake-ngii-region'
import { Database } from 'bun:sqlite'

test('free-space reserve defaults to 20 GiB and accepts a lower explicit reserve', () => {
  expect(parseReserveGiB()).toBe(20)
  expect(parseReserveGiB('5.0')).toBe(5)
  for (const bad of ['0.5', 'abc', '-3', 'Infinity']) expect(() => parseReserveGiB(bad)).toThrow('--reserve-gib')
})

test('database CLI rejects incomplete sources before opening or hashing terrain', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'ngii-incomplete-'))
  const planSHA256 = 'a'.repeat(64), dbPath = join(folder, 'input.sqlite')
  const db = new Database(dbPath)
  db.exec('CREATE TABLE metadata(key,value); CREATE TABLE sources(id,expected_rows,next_row,status,manifest); CREATE TABLE issues(kind); CREATE TABLE buildings(id)')
  db.query('INSERT INTO metadata VALUES(?,?)').run('planSHA256', planSHA256)
  db.query('INSERT INTO sources VALUES(?,?,?,?,?)').run('source', 1, 0, 'partial', '{}')
  db.close()
  const plan = { schema: 'ngii-canonical-plan-v1', storageSchema: 'canonical-sqlite-v2', planSHA256, expectedRows: 1, sources: [{ id: 'source', expectedRows: 1, manifest: {} }] }
  const inventory = { schema: 'ngii-canonical-regions-v1', planSHA256, sourceComplete: true, sourceRows: 1, buildingCount: 1, regionCount: 1, regions: [{ region14: '14/1/2', buildings: 1, components: 1 }] }
  try {
    await writeFile(join(folder, 'plan.json'), JSON.stringify(plan))
    await writeFile(join(folder, 'regions.json'), JSON.stringify(inventory))
    await expect(main(['--database', dbPath, '--regions', join(folder, 'regions.json'), '--source-plan', join(folder, 'plan.json'), '--terrain', join(folder, 'does-not-exist.pmtiles'), '--terrain-sha256', 'b'.repeat(64), '--output', join(folder, 'output')])).rejects.toThrow('ingest incomplete')
  } finally { await rm(folder, { recursive: true, force: true }) }
})

test('region selection is bounded, deterministic and rejects unknown owners', () => {
  const rows = [{ region14: '14/2/3' }, { region14: '14/1/2' }]
  expect(selectRegions(rows, undefined, 1)).toEqual([rows[1]!])
  expect(selectRegions(rows, '14/2/3')).toEqual([rows[0]!])
  expect(() => selectRegions(rows, '14/9/9')).toThrow()
  expect(() => selectRegions(rows, undefined, 0)).toThrow()
})

test('immutable resume verifies identity and payload; missing receipt cannot resume', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'ngii-resume-'))
  const bytes = Buffer.from('mesh'), sha256 = createHash('sha256').update(bytes).digest('hex')
  const identity = { owner: '14/1/2', terrainSHA256: 'a'.repeat(64), inputSHA256: 'b'.repeat(64) }
  try {
    await expect(verifyExistingCandidate(folder, identity)).rejects.toThrow()
    await writeFile(join(folder, 'part.b3dm'), bytes)
    await writeFile(join(folder, 'candidate-receipt.json'), JSON.stringify({ ...identity, files: [{ path: 'part.b3dm', bytes: bytes.length, sha256 }] }))
    expect(await verifyExistingCandidate(folder, identity)).toBeTrue()
    await expect(verifyExistingCandidate(folder, { ...identity, terrainSHA256: 'c'.repeat(64) })).rejects.toThrow('identity')
    await writeFile(join(folder, 'part.b3dm'), 'changed')
    await expect(verifyExistingCandidate(folder, identity)).rejects.toThrow('payload')
  } finally { await rm(folder, { recursive: true, force: true }) }
})


test('snapshot CLI rejects unfinished nationwide input before terrain access', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'ngii-snapshot-incomplete-'))
  try {
    await writeFile(join(folder, 'snapshot.json'), JSON.stringify({ schema: 'ngii-canonical-snapshot-v1', complete: false }))
    await writeFile(join(folder, 'plan.json'), JSON.stringify({ schema: 'ngii-canonical-plan-v1', planSHA256: 'a'.repeat(64), sources: [{ manifest: {} }] }))
    await expect(main(['--snapshot', join(folder, 'snapshot.json'), '--source-plan', join(folder, 'plan.json'), '--terrain', join(folder, 'missing.pmtiles'), '--terrain-sha256', 'b'.repeat(64), '--output', join(folder, 'out')])).rejects.toThrow('snapshot incomplete')
  } finally { await rm(folder, { recursive: true, force: true }) }
})


test('region-local mesh packing shares exact bytes while preserving LOD node metadata', async () => {
  const saved = new Map<string, Uint8Array>()
  const write = createRegionMeshWriter(async (uri, bytes) => { saved.set(uri, bytes.slice()) })
  const bytes = new Uint8Array([1,2,3]), nodes = []
  for (const [z, error] of [[16,0],[15,12],[14,24]]) {
    nodes.push({ boundingVolume: { region: [z,1,2,3,4,5] }, geometricError:error, refine:'REPLACE',
      content:{uri:await write(`${z}-1-2.b3dm`,bytes.slice())} })
  }
  expect(saved.size).toBe(1)
  expect(nodes.map(n=>n.geometricError)).toEqual([0,12,24])
  expect(nodes.map(n=>n.boundingVolume.region[0])).toEqual([16,15,14])
  expect(new Set(nodes.map(n=>n.content.uri)).size).toBe(1)
  expect(await write('different.b3dm',new Uint8Array([1,2,4]))).toBe('different.b3dm.gz')
  expect(saved.size).toBe(2)
  expect(new Uint8Array(gunzipSync(saved.get(nodes[0]!.content.uri)!))).toEqual(bytes)
})

test('packing does not remember a failed write, and resume rejects old packing revision', async () => {
  let calls=0
  const write=createRegionMeshWriter(async()=>{if(++calls===1)throw Error('disk failure')})
  await expect(write('a.b3dm',new Uint8Array([1]))).rejects.toThrow('disk failure')
  expect(await write('a.b3dm',new Uint8Array([1]))).toBe('a.b3dm.gz')
  expect(calls).toBe(2)
  const folder=await mkdtemp(join(tmpdir(),'ngii-packing-'))
  try {
    await writeFile(join(folder,'candidate-receipt.json'),JSON.stringify({assetPacking:'old',files:[]}))
    await expect(verifyExistingCandidate(folder,{assetPacking:NGII_ASSET_PACKING})).rejects.toThrow('identity')
  } finally {await rm(folder,{recursive:true,force:true})}
})


test('gzip packing is deterministic and resume verifies encoded and decoded hashes', async () => {
  const folder=await mkdtemp(join(tmpdir(),'ngii-gzip-'))
  const original=Buffer.from('b3dm'+'fixture'.repeat(100))
  let file:any, first:Uint8Array|undefined
  try {
    const save=async(name:string,bytes:Uint8Array,encoding:Record<string,unknown>)=>{
      await writeFile(join(folder,name),bytes);first=bytes
      file={path:name,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),...encoding}
    }
    await createRegionMeshWriter(save)('tile.b3dm',original)
    await createRegionMeshWriter(async(_name,bytes)=>{expect(bytes).toEqual(first!);expect([...bytes.slice(4,8)]).toEqual([0,0,0,0])})('other.b3dm',original)
    const receipt={assetPacking:NGII_ASSET_PACKING,files:[file]}
    await writeFile(join(folder,'candidate-receipt.json'),JSON.stringify(receipt))
    expect(await verifyExistingCandidate(folder,{assetPacking:NGII_ASSET_PACKING})).toBeTrue()
    file.decodedSHA256='f'.repeat(64)
    await writeFile(join(folder,'candidate-receipt.json'),JSON.stringify(receipt))
    await expect(verifyExistingCandidate(folder,{assetPacking:NGII_ASSET_PACKING})).rejects.toThrow('decoded')
    const invalid=Buffer.from('not gzip');await writeFile(join(folder,file.path),invalid)
    file.bytes=invalid.length;file.sha256=createHash('sha256').update(invalid).digest('hex')
    await writeFile(join(folder,'candidate-receipt.json'),JSON.stringify(receipt))
    await expect(verifyExistingCandidate(folder,{assetPacking:NGII_ASSET_PACKING})).rejects.toThrow()
  } finally {await rm(folder,{recursive:true,force:true})}
})


test('compressed metadata preserves full JSON bytes and cannot resume with corrupt decoded identity', async () => {
  const folder=await mkdtemp(join(tmpdir(),'ngii-json-gzip-'))
  const value={buildings:[{id:'a',provenance:{source:'official',row:0},holes:[[[1,2],[3,4]]]}]}
  const decoded=Buffer.from(JSON.stringify(value)), encoded=encodeCandidatePayload(decoded)
  expect(encodeCandidatePayload(decoded)).toEqual(encoded)
  expect(gunzipSync(encoded.bytes).equals(decoded)).toBeTrue()
  try {
    const files=[]
    for(const name of ['footprints.json.gz','ground-source.json.gz']) {
      await writeFile(join(folder,name),encoded.bytes)
      files.push({path:name,bytes:encoded.bytes.length,sha256:createHash('sha256').update(encoded.bytes).digest('hex'),...encoded.metadata})
    }
    const receipt={assetPacking:NGII_ASSET_PACKING,files}
    await writeFile(join(folder,'candidate-receipt.json'),JSON.stringify(receipt))
    expect(await verifyExistingCandidate(folder,{assetPacking:NGII_ASSET_PACKING})).toBeTrue()
    files[1]!.decodedBytes++
    await writeFile(join(folder,'candidate-receipt.json'),JSON.stringify(receipt))
    await expect(verifyExistingCandidate(folder,{assetPacking:NGII_ASSET_PACKING})).rejects.toThrow('decoded')
  } finally {await rm(folder,{recursive:true,force:true})}
})


const stagedName='14-1-2-aaaaaaaaaaaaaaaa'
const stagedIdentity={owner:'14/1/2',assetPacking:NGII_ASSET_PACKING}
const fileReceipt=(path:string,bytes:Uint8Array,extra={})=>({path,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),...extra})

test('reserve failure resumes pinned staging without rewriting complete files; final appears only after receipt',async()=>{
  const output=await mkdtemp(join(tmpdir(),'ngii-stage-resume-'))
  let enough=true
  const check=async()=>{if(!enough)throw Error('20GiB reserve')}
  try {
    const first=await createCandidateStage(output,stagedName,stagedIdentity,check)
    const tree=Buffer.from('{"root":{}}'),metadata=encodeCandidatePayload(Buffer.from('{"buildings":[]}'))
    await first.save('tileset.json',tree)
    const before=await stat(join(first.folder,'tileset.json'),{bigint:true})
    enough=false
    await expect(first.save('ground-source.json.gz',metadata.bytes)).rejects.toThrow('reserve')
    await expect(stat(first.final)).rejects.toThrow()
    // A terminated write may leave only its private .part bytes.
    await writeFile(join(first.folder,'ground-source.json.gz.part'),'interrupted')
    enough=true
    const resumed=await createCandidateStage(output,stagedName,stagedIdentity,check)
    await resumed.save('tileset.json',tree)
    expect((await stat(join(resumed.folder,'tileset.json'),{bigint:true})).mtimeNs).toBe(before.mtimeNs)
    await resumed.save('ground-source.json.gz',metadata.bytes)
    await expect(stat(resumed.final)).rejects.toThrow()
    const receipt={...stagedIdentity,files:[fileReceipt('tileset.json',tree),fileReceipt('ground-source.json.gz',metadata.bytes,metadata.metadata)]}
    await resumed.finish(receipt)
    expect(await verifyExistingCandidate(resumed.final,stagedIdentity)).toBeTrue()
    expect(await readFile(join(resumed.final,'tileset.json'))).toEqual(tree)
    await expect(stat(resumed.folder)).rejects.toThrow()
  } finally {await rm(output,{recursive:true,force:true})}
})

test('wrong stage identity or completed bytes fail; existing final is never overwritten',async()=>{
  const output=await mkdtemp(join(tmpdir(),'ngii-stage-corrupt-'))
  try {
    const stage=await createCandidateStage(output,stagedName,stagedIdentity,async()=>{})
    await expect(createCandidateStage(output,stagedName,{...stagedIdentity,owner:'changed'},async()=>{})).rejects.toThrow('identity')
    const bytes=Buffer.from('{}');await stage.save('tileset.json',bytes)
    await writeFile(join(stage.folder,'tileset.json'),'corrupt')
    await expect(stage.save('tileset.json',bytes)).rejects.toThrow('payload mismatch')
    await expect(stat(stage.final)).rejects.toThrow()
    await writeFile(join(stage.folder,'tileset.json'),bytes)
    await mkdir(stage.final);await writeFile(join(stage.final,'sentinel'),'original')
    await expect(stage.finish({...stagedIdentity,files:[fileReceipt('tileset.json',bytes)]})).rejects.toThrow('already exists')
    expect(await readFile(join(stage.final,'sentinel'),'utf8')).toBe('original')
    expect((await stat(stage.folder)).isDirectory()).toBeTrue()
  } finally {await rm(output,{recursive:true,force:true})}
})

test('atomic rename retries Windows busy errors only within bounded attempts',async()=>{
  const output=await mkdtemp(join(tmpdir(),'ngii-stage-rename-'))
  try {
    const from=join(output,'from'),to=join(output,'to');await writeFile(from,'same bytes')
    let attempts=0;const waits:number[]=[]
    await renameCandidateAtomically(from,to,async(a,b)=>{if(++attempts<3)throw Object.assign(Error('busy'),{code:'EPERM'});await rename(a,b)},async ms=>{waits.push(ms)})
    expect(attempts).toBe(3);expect(waits).toEqual([25,50]);expect(await readFile(to,'utf8')).toBe('same bytes')
    let failures=0
    await expect(renameCandidateAtomically(to,join(output,'never'),async()=>{failures++;throw Object.assign(Error('busy'),{code:'EBUSY'})},async()=>{})).rejects.toThrow('busy')
    expect(failures).toBe(5);expect(await readFile(to,'utf8')).toBe('same bytes')
  } finally {await rm(output,{recursive:true,force:true})}
})


test('two shards partition the same sorted bounded inventory without changing owner order',()=>{
 const rows=[{region14:'14/3/1'},{region14:'14/1/1'},{region14:'14/2/1'}]
 const selected=selectRegions(rows),a=shardRegions(selected,0,2),b=shardRegions(selected,1,2)
 expect(a.map(r=>r.region14)).toEqual(['14/1/1','14/3/1']);expect(b.map(r=>r.region14)).toEqual(['14/2/1'])
 expect(new Set([...a,...b].map(r=>r.region14)).size).toBe(selected.length)
 expect(shardRegions(selected)).toEqual(selected)
 expect(()=>shardRegions(selected,2,2)).toThrow();expect(()=>shardRegions(selected,0,3)).toThrow()
})

test('parallel children require the single initialized pin and never race to create it',async()=>{
 const folder=await mkdtemp(join(tmpdir(),'ngii-shard-pin-')),path=join(folder,'candidate-inputs.json'),identity={source:'same',terrain:'same'}
 try{
  await expect(bindCandidateInputs(path,identity,true)).rejects.toThrow('initialized by coordinator')
  await bindCandidateInputs(path,identity)
  const bytes=await readFile(path)
  await Promise.all([bindCandidateInputs(path,identity,true),bindCandidateInputs(path,identity,true)])
  expect(await readFile(path)).toEqual(bytes)
  await expect(bindCandidateInputs(path,{...identity,terrain:'changed'},true)).rejects.toThrow('identity mismatch')
  await writeFile(path,JSON.stringify(identity,null,2))
  await expect(bindCandidateInputs(path,identity,true)).resolves.toBeUndefined()
 }finally{await rm(folder,{recursive:true,force:true})}
})
