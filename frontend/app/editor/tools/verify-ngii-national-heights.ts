import { createHash, randomUUID } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { mkdir, readFile, readdir, writeFile, rename, unlink, stat, statfs, link } from 'node:fs/promises'
import { join, resolve, relative, isAbsolute, basename } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import { gunzipSync, inflateSync } from 'node:zlib'
import { PMTiles } from 'pmtiles'
import { openCanonicalSnapshot, type CanonicalPlan, type CanonicalRegionInventory } from './ngii-canonical-source'
import { verifyExistingCandidate, NGII_ASSET_PACKING, selectRegions } from './bake-ngii-region'
import { openLocalArchive } from './local-building-archive'
import { decodeHeightTile } from '../features/world/lib/terrain-archive'
import { createTerrainHeightContract, TERRAIN_HEIGHT_CONTRACT } from '../features/world/lib/terrain-height-contract'
import { BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import type { CanonicalBuilding, TerrainSample } from './ngii-mesh-input'

const hash = (bytes: string | Uint8Array) => createHash('sha256').update(bytes).digest('hex')
export const canonicalJSON = (value: unknown): string => JSON.stringify(value, (_k, v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0)) : v)
const fileSHA = async (path: string) => { const h=createHash('sha256');for await(const b of createReadStream(path))h.update(b);return h.digest('hex') }
const readJSON = async (path: string) => JSON.parse(await readFile(path,'utf8'))
async function atomic(path: string,value: unknown) { await writeFile(path+'.part',JSON.stringify(value,null,2));await rename(path+'.part',path) }
type Ground = { id: string; sourceUFID: string|null; ground: TerrainSample; provenance: CanonicalBuilding['provenance']; heightSource: CanonicalBuilding['heightSource'] }
type Footprint = { key: string; z: number }
type Native = (points: number[][]) => Promise<(number|null)[]>
export type RegionProof = { owner: string; buildings: number; components: number; inputSHA256: string; supportedGroundBuildings: number; unresolvedGroundBuildings: number; nativeFinite: number; nativeNoData: { key: string; classification: 'ancestor-supported'|'declared-ellipsoid-zero' }[]; displayMaximum: number|null; nativeOver: number; datumMaximum: number; errors: { key: string; kind: string; error: number }[]; passed: boolean; nativeEvidence: 'recorded'|'insufficient' }
/** Native DEM vs displayed terrain disagreement is recorded, never a gate: buildings follow the served terrain. */
export const NATIVE_RECORD_THRESHOLD_METRES = .5

/** Independent resampling uses canonical anchors, never metadata vertices or the stored ground as its input. */
export async function verifyRegion(owner: string, rows: Iterable<CanonicalBuilding>, grounds: Ground[], footprints: Footprint[], sample: (lon:number,lat:number)=>Promise<TerrainSample>, native: Native, batchSize=256): Promise<RegionProof> {
  if(!Number.isInteger(batchSize)||batchSize<1||batchSize>4096)throw Error('Invalid verification batch size')
  const byId=new Map(grounds.map(g=>[g.id,g])), byKey=new Map(footprints.map(f=>[f.key,f]))
  if(byId.size!==grounds.length||byKey.size!==footprints.length)throw Error('Duplicate ground/component identity')
  const proof:RegionProof={owner,buildings:0,components:0,inputSHA256:'',supportedGroundBuildings:0,unresolvedGroundBuildings:0,nativeFinite:0,nativeNoData:[],displayMaximum:null,nativeOver:0,datumMaximum:0,errors:[],passed:false,nativeEvidence:'insufficient'}
  const input=createHash('sha256');let batch:CanonicalBuilding[]=[]
  const consume=async()=>{
    const heights=await native(batch.map(r=>r.anchorWGS84))
    if(heights.length!==batch.length||heights.some(h=>h!==null&&(!Number.isFinite(h)||typeof h!=='number')))throw Error('Missing or invalid native response')
    for(let n=0;n<batch.length;n++){
      const row=batch[n]!,id=row.canonicalBuildingId,record=byId.get(id)
      if(!record||canonicalJSON(record.provenance)!==canonicalJSON(row.provenance)||record.sourceUFID!==row.sourceUFID||canonicalJSON(record.heightSource)!==canonicalJSON(row.heightSource))throw Error('Canonical ground provenance mismatch')
      const actual=await sample(row.anchorWGS84[0]!,row.anchorWGS84[1]!),g=record.ground
      if(!Number.isFinite(actual.height)||actual.contract!==TERRAIN_HEIGHT_CONTRACT||!actual.sourceLevels.length||actual.ellipsoidZero!==actual.sourceLevels.includes(-1)||g.archiveSha256!==actual.archiveSha256||g.contract!==actual.contract||g.ellipsoidZero!==actual.ellipsoidZero||canonicalJSON(g.sourceLevels)!==canonicalJSON(actual.sourceLevels)||!Number.isFinite(g.height))throw Error('Ground source policy mismatch')
      actual.ellipsoidZero?proof.unresolvedGroundBuildings++:proof.supportedGroundBuildings++
      const datum=Math.abs(g.height-actual.height);proof.datumMaximum=Math.max(proof.datumMaximum,datum)
      if(datum>.01)proof.errors.push({key:id,kind:'ground-datum',error:datum})
      const count=row.geomWGS84.type==='Polygon'?1:row.geomWGS84.coordinates.length
      for(let i=0;i<count;i++){
        const key=`${id}/${i}`,f=byKey.get(key)
        if(!f||!Number.isFinite(f.z))throw Error('Missing canonical component')
        const error=Math.max(Math.abs(f.z-actual.height),Math.abs(f.z-g.height));proof.datumMaximum=Math.max(proof.datumMaximum,error)
        if(error>.01)proof.errors.push({key,kind:'component-datum',error})
        proof.components++;byKey.delete(key)
      }
      const reference=heights[n]!
      if(reference===null)proof.nativeNoData.push({key:id,classification:actual.ellipsoidZero?'declared-ellipsoid-zero':'ancestor-supported'})
      else {const error=Math.abs(actual.height-reference);proof.nativeFinite++;proof.displayMaximum=Math.max(proof.displayMaximum??0,error);if(error>NATIVE_RECORD_THRESHOLD_METRES)proof.nativeOver++}
      byId.delete(id);proof.buildings++
    }
    batch=[]
  }
  for(const row of rows){input.update(JSON.stringify(row)+'\n');batch.push(row);if(batch.length>=batchSize)await consume()}
  if(batch.length)await consume()
  if(byId.size||byKey.size)throw Error('Extra noncanonical ground/component')
  proof.inputSHA256=input.digest('hex');proof.passed=proof.errors.length===0;proof.nativeEvidence=proof.nativeFinite?'recorded':'insufficient'
  return proof
}

/** Persisted receipts are reusable only under the identical pinned run and candidate bytes. */
export function reusableProof(value:any,runSHA:string,receiptSHA:string):RegionProof|undefined {
  if(!value)return undefined
  if(value.runSHA256!==runSHA||value.receiptSHA256!==receiptSHA||value.proofSHA256!==hash(canonicalJSON(value.proof)))throw Error('Verification checkpoint identity/hash mismatch')
  return value.proof
}

export function validateCompletedInventoryPin(pin: any, binding: Record<string,string>, plan: CanonicalPlan, inventory: CanonicalRegionInventory) {
  if(Object.entries(binding).some(([k,v])=>pin[k]!==v))throw Error('Completed inventory pin mismatch')
  if(plan.schema!=='ngii-canonical-plan-v1'||plan.storageSchema!=='canonical-sqlite-v2'||inventory.schema!=='ngii-canonical-regions-v1'||!inventory.sourceComplete||inventory.planSHA256!==plan.planSHA256||inventory.sourceRows!==plan.expectedRows||inventory.regionCount!==inventory.regions.length||new Set(inventory.regions.map(r=>r.region14)).size!==inventory.regionCount||inventory.regions.reduce((s,r)=>s+r.buildings,0)!==inventory.buildingCount||inventory.regions.some(r=>!/^14\/\d+\/\d+$/.test(r.region14)||!Number.isInteger(r.buildings)||r.buildings<1||!Number.isInteger(r.components)||r.components<r.buildings))throw Error('Invalid completed inventory')
}

type CompactProof = Omit<RegionProof,'nativeNoData'|'errors'> & { nativeNoDataCount:number }
export function verificationProgress(proofs: Pick<RegionProof,'components'|'passed'|'nativeFinite'>[], expectedRegions:number, expectedComponents:number, sampleOnly:boolean, stopped=false) {
  const compared=proofs.reduce((n,p)=>n+p.components,0),nativeFinite=proofs.reduce((n,p)=>n+p.nativeFinite,0)
  if(proofs.length>expectedRegions||compared>expectedComponents)throw Error('Verification exceeds pinned inventory')
  const complete=!sampleOnly&&!stopped&&proofs.length===expectedRegions&&compared===expectedComponents
  return {complete,passed:complete&&nativeFinite>0&&proofs.every(p=>p.passed),pendingRegions:expectedRegions-proofs.length,expectedComponents,compared,nativeFinite}
}

export async function discoverCompletedCandidates(regional:string,wanted:Set<string>,found:Map<string,string>) {
      for(const entry of await readdir(regional,{withFileTypes:true})){
        const match=/^14-(\d+)-(\d+)-[a-f0-9]{16}$/.exec(entry.name)
        if(!entry.isDirectory()||!match)continue
        const owner=`14/${match[1]}/${match[2]}`;if(!wanted.has(owner))continue
        const folder=join(regional,entry.name),prior=found.get(owner)
        if(prior){if(prior!==folder)throw Error('Duplicate regional candidate');continue}
        const receipt=await readJSON(join(folder,'candidate-receipt.json'))
        if(receipt.owner!==owner||receipt.completeRegion!==true)throw Error('Invalid completed regional candidate')
        found.set(owner,folder)
      }
    }

/** Cheap identity of every receipt payload file, taken at full verification. Any write, replacement or resize changes it. */
export type FileStamp = { path:string; size:string; mtimeNs:string; ino:string }
export async function candidateFileStamps(folder:string,receipt:any):Promise<FileStamp[]> {
  if(!Array.isArray(receipt?.files)||!receipt.files.length)throw Error('Missing candidate payload receipt')
  return Promise.all(receipt.files.map(async(file:any)=>{
    if(typeof file.path!=='string'||basename(file.path)!==file.path||file.path.includes('\\')||file.path==='..'||file.path==='.')throw Error('Invalid candidate payload path')
    const s=await stat(join(folder,file.path),{bigint:true});return {path:file.path,size:String(s.size),mtimeNs:String(s.mtimeNs),ino:String(s.ino)}
  }))
}
/** A shard-verified region skips payload re-hashing only under the same run, the same receipt bytes and unchanged file stamps. */
export function stampedReuse(previous:any,runSHA:string,receiptSHA:string,current:FileStamp[]):boolean {
  return Boolean(previous&&previous.runSHA256===runSHA&&previous.receiptSHA256===receiptSHA&&Array.isArray(previous.fileStamps)&&previous.fileStamps.length&&canonicalJSON(previous.fileStamps)===canonicalJSON(current))
}

const errno=(e:unknown)=>(e as NodeJS.ErrnoException).code
const pidAlive=(pid:number)=>{try{process.kill(pid,0);return true}catch(e){return errno(e)==='EPERM'}}
/** True when a lock is held by a live (or unidentifiable) owner. A lock whose recorded pid is dead is removed. */
async function liveLock(path:string) {
  let text:string;try{text=(await readFile(path,'utf8')).trim()}catch(e){if(errno(e)==='ENOENT')return false;throw e}
  if(!/^\d+$/.test(text)||pidAlive(Number(text)))return true
  try{await unlink(path)}catch(e){if(errno(e)!=='ENOENT')throw e}
  return false
}
export const SHARD_LOCK=/^verification-shard-\d+(-of-\d+)?\.lock$/
/** Shards and the unsharded merge exclude each other: the merge refuses live shard locks, shards refuse a live merge lock. */
export async function acquireVerificationLock(work:string,tag:string) {
  const own=join(work,`verification${tag}.lock`)
  for(let attempt=0;;attempt++){
    try{await writeFile(own,String(process.pid),{flag:'wx'});break}
    catch(e){if(errno(e)!=='EEXIST')throw e;if(attempt||await liveLock(own))throw Error(`Verification lock ${own} is held by a live process`)}
  }
  try{
    const others=tag?['verification.lock']:(await readdir(work)).filter(n=>SHARD_LOCK.test(n))
    for(const name of others)if(await liveLock(join(work,name)))throw Error(`Verification ${tag?'merge':'shard'} lock ${name} is live`)
  }catch(e){await unlink(own);throw e}
  return own
}
/** Concurrent shards race to pin the run identity: write a private .part, hard-link without overwrite, re-read on EEXIST. */
export async function pinVerificationInputs(pin:string,identity:unknown,attempts=40) {
  for(let attempt=0;;attempt++){
    let text:string|undefined
    try{text=await readFile(pin,'utf8')}catch(e){if(errno(e)!=='ENOENT')throw e}
    if(text===undefined){
      const part=`${pin}.${process.pid}-${randomUUID()}.part`;await writeFile(part,JSON.stringify(identity,null,2),{flag:'wx'})
      try{await link(part,pin);return}catch(e){if(errno(e)!=='EEXIST')throw e}finally{await unlink(part)}
    } else {
      let value:unknown,parsed=false;try{value=JSON.parse(text);parsed=true}catch{}
      if(parsed){if(canonicalJSON(value)!==canonicalJSON(identity))throw Error('Verification input identity changed');return}
    }
    if(attempt>=attempts)throw Error('Verification input pin unreadable')
    await new Promise(r=>setTimeout(r,50))
  }
}

function belowNormal(pid:number) {
  if(process.platform!=='win32'||!Number.isInteger(pid)||pid<1)throw Error('BelowNormal requires a valid Windows owned process')
  const r=spawnSync('powershell',['-NoProfile','-NonInteractive','-Command',`[System.Diagnostics.Process]::GetProcessById(${pid}).PriorityClass = 'BelowNormal'`],{windowsHide:true,encoding:'utf8'})
  if(r.error||r.status!==0)throw Error('Could not set owned process BelowNormal')
}

export class NativeWorker {
  child:ReturnType<typeof spawn>; lines:AsyncIterator<string>;ready:any;next=0
  constructor(command:string,args:string[],lowPriority=false){this.child=spawn(command,args,{windowsHide:true,env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1',MKL_NUM_THREADS:'1',GDAL_CACHEMAX:'64'},stdio:['pipe','pipe','inherit']});this.child.on('error',()=>{});if(lowPriority){try{belowNormal(this.child.pid!)}catch(e){this.child.kill();throw e}}this.lines=createInterface({input:this.child.stdout!})[Symbol.asyncIterator]()}
  async line(){let timer:ReturnType<typeof setTimeout>|undefined;const value=await Promise.race([this.lines.next(),new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(Error('Native worker response timeout')),120000)})]).finally(()=>clearTimeout(timer));if(value.done)throw Error('Native worker closed unexpectedly');const r=JSON.parse(value.value);if(r.type==='error')throw Error(`Native worker: ${r.error}`);return r}
  async start(){this.ready=await this.line();if(this.ready.type!=='ready')throw Error('Native worker not ready');return this.ready}
  async request(value:unknown){const id=++this.next;this.child.stdin!.write(JSON.stringify({id,...value as object})+'\n');const r=await this.line();if(r.id!==id||['sourceVrtSHA256','sourceFilesSHA256','recursiveSourceFilesSHA256'].some(k=>r[k]!==this.ready[k]))throw Error('Native worker source/response mismatch');return r}
  async sample(points:number[][]){return (await this.request({points})).heights as (number|null)[]}
  async close(){const r=await this.request({op:'close'});if(r.type!=='closed')throw Error('Native worker final validation missing');this.child.stdin!.end()}
  stop(){this.child.kill()}
}

export async function main(args=process.argv.slice(2)) {
  const option=(key:string)=>{const i=args.indexOf(key);if(i<0||!args[i+1])throw Error('Missing '+key);return args[i+1]!}
  const watch=args.includes('--watch'),pollSeconds=args.includes('--poll-seconds')?Number(option('--poll-seconds')):30
  if(!Number.isFinite(pollSeconds)||pollSeconds<1||pollSeconds>60)throw Error('Poll interval must be 1..60 seconds')
  if(args.includes('--below-normal'))belowNormal(process.pid)
  const dataRoot=resolve(option('--data-root'))
  const snapshot=resolve(option('--snapshot')),planPath=resolve(option('--plan')),inventoryPath=resolve(option('--regions')),regional=resolve(option('--regional-root')),work=resolve(option('--work')),terrain=resolve(option('--terrain')),receiptPath=resolve(option('--terrain-receipt')),vrt=resolve(option('--dem'))
  const plan=await readJSON(planPath) as CanonicalPlan,inventory=await readJSON(inventoryPath) as CanonicalRegionInventory,terrainReceipt=await readJSON(receiptPath),terrainSHA=terrainReceipt.sha256
  const publicRelative=relative(join(dataRoot,'world-buildings'),regional)
  if(!publicRelative||publicRelative.startsWith('..')||isAbsolute(publicRelative))throw Error('Regional root must be below DATA_ROOT/world-buildings')
  const python=option('--python'),workerPath=fileURLToPath(new URL('./ngii-native-height-worker.py',import.meta.url))
  if(work===resolve(receiptPath,'..')||work===regional||work===resolve(terrain,'..'))throw Error('Verification work must be a new separate evidence directory')
  const check=spawnSync(python,['-X','utf8',fileURLToPath(new URL('../../../../infra/data/ngii_canonical_snapshot.py',import.meta.url)),'verify','--snapshot',snapshot,'--plan',planPath],{encoding:'utf8',windowsHide:true,env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1',MKL_NUM_THREADS:'1'}})
  if(check.status!==0||check.error)throw Error('Completed canonical snapshot gate failed')
  if(await fileSHA(terrain)!==terrainSHA)throw Error('Terrain archive SHA mismatch')
  const selected=selectRegions(inventory.regions,args.includes('--region')?option('--region'):undefined,args.includes('--sample-regions')?Number(option('--sample-regions')):undefined),sampleOnly=args.includes('--region')||args.includes('--sample-regions')
  // --shard k/n splits regions across processes sharing one work folder. Proofs are per region and bound to the
  // full run identity, so a final unsharded run reuses them and alone writes the national summary.
  const shard=args.includes('--shard')?/^(\d+)\/(\d+)$/.exec(option('--shard')):undefined
  if(args.includes('--shard')&&(!shard||Number(shard[2])<2||Number(shard[1])>=Number(shard[2])))throw Error('Shard must be k/n with 0<=k<n and n>=2')
  const mine=shard?selected.filter((_,i)=>i%Number(shard[2])===Number(shard[1])):selected,tag=shard?`-shard-${shard[1]}-of-${shard[2]}`:''
  const planSHA=await fileSHA(planPath),inventorySHA=await fileSHA(inventoryPath),snapshotSHA=await fileSHA(snapshot),queuePath=args.includes('--queue-inputs')?resolve(option('--queue-inputs')):join(regional,'queue-inputs.json')
  validateCompletedInventoryPin(await readJSON(queuePath),{snapshotSHA256:snapshotSHA,planFileSHA256:planSHA,terrainSHA256:terrainSHA,terrainPath:terrain,regionsPath:inventoryPath,output:regional,regionsSHA256:inventorySHA},plan,inventory)
  const identity={schema:'ngii-national-heights-v1',snapshotSHA256:snapshotSHA,queueInputsSHA256:await fileSHA(queuePath),planFileSHA256:planSHA,inventorySHA256:inventorySHA,terrainSHA256:terrainSHA,terrainReceiptSHA256:await fileSHA(receiptPath),implementationSHA256:await fileSHA(fileURLToPath(import.meta.url)),contractImplementationSHA256:await fileSHA(fileURLToPath(new URL('../features/world/lib/terrain-height-contract.ts',import.meta.url))),nativeWorkerSHA256:await fileSHA(workerPath),nativeSourceReaderSHA256:await fileSHA(fileURLToPath(new URL('./incremental_terrain_archive.py',import.meta.url))),canonicalReaderSHA256:await fileSHA(fileURLToPath(new URL('./ngii-canonical-source.ts',import.meta.url))),regionalRoot:regional,sampleOnly,selected:selected.map(r=>r.region14)}
  const runSHA=hash(canonicalJSON(identity));await mkdir(work,{recursive:true})
  const reserve=args.includes('--reserve-gib')?Number(option('--reserve-gib')):20;if(!(reserve>=1))throw Error('Invalid --reserve-gib')
  const checkSpace=async()=>{const s=await statfs(work);if(s.bavail*s.bsize<reserve*1024**3)throw Error(`needs_storage: verification requires ${reserve}GiB reserve`)}
  await checkSpace()
  const lock=await acquireVerificationLock(work,tag)
  let db:ReturnType<typeof openCanonicalSnapshot>|undefined,local:Awaited<ReturnType<typeof openLocalArchive>>|undefined,worker:NativeWorker|undefined
  try {
    await pinVerificationInputs(join(work,'verification-inputs.json'),identity)
    db=openCanonicalSnapshot(snapshot);db.exec('PRAGMA query_only=ON; BEGIN')
    // The completed inventory is already bound to this exact frozen snapshot by the coordinator.
    // Recounting 22M rows for a one-region probe adds no new evidence; verify selected rows below.
    const query=db.query<{id:string;payload:Uint8Array},[string]>('SELECT id,payload FROM buildings WHERE region14=? ORDER BY region16,id')
    function* rows(owner:string):Generator<CanonicalBuilding>{
      for(const stored of query.iterate(owner)){
        const r=JSON.parse(inflateSync(stored.payload).toString()),ref=r.provenance,source=plan.sources.find(s=>s.id===ref.sourceId)
        if(!source||r.canonicalBuildingId!==stored.id||!Number.isInteger(ref.row)||ref.row<0||ref.row>=source.expectedRows)throw Error('Invalid canonical row provenance')
        r.provenance={...source.manifest,row:ref.row};yield r
      }
    }
    const found=new Map<string,string>(),wanted=new Set(selected.map(r=>r.region14))
    const discover=()=>discoverCompletedCandidates(regional,wanted,found)
    await discover()
    if(!watch&&found.size!==selected.length)throw Error('Requested regions not yet generated')
    local=await openLocalArchive(terrain);const archive=new PMTiles(local),meta=await archive.getMetadata() as any
    if(meta.schema!=='ngii-heightmap-v1'||meta.size!==33||meta.archiveZoomOffset!==1||meta.grid!=='Cesium.GeographicTilingScheme'||meta.vrt_sha256!==terrainReceipt.vrt_sha256)throw Error('Invalid archive metadata')
    const contract=createTerrainHeightContract(async({level,x,y})=>{const t=await archive.getZxy(level+1,x,y);return t?decodeHeightTile(t.data):null},{archiveSha256:terrainSHA,minLevel:meta.minLevel,maxLevel:meta.maxLevel,keep:128})
    const workerArgs=['-X','utf8',workerPath,'--vrt',vrt,'--source-vrt-sha256',meta.vrt_sha256,'--source-files-sha256',terrainReceipt.metadata.sourceFilesSHA256]
    if(terrainReceipt.metadata.recursiveSourceFilesSHA256)workerArgs.push('--recursive-source-files-sha256',terrainReceipt.metadata.recursiveSourceFilesSHA256)
    worker=new NativeWorker(python,workerArgs,args.includes('--below-normal'));const nativeReady=await worker.start()
    const pins:{owner:string;receiptSHA256:string;uri:string}[]=[],proofs:CompactProof[]=[],done=new Set<string>();await mkdir(join(work,'regions'),{recursive:true})
    const monitored=[snapshot,planPath,inventoryPath,queuePath,receiptPath,terrain,fileURLToPath(import.meta.url),workerPath,fileURLToPath(new URL('../features/world/lib/terrain-height-contract.ts',import.meta.url)),fileURLToPath(new URL('./ngii-canonical-source.ts',import.meta.url)),fileURLToPath(new URL('./incremental_terrain_archive.py',import.meta.url))],stamps=new Map<string,string>()
    const stamp=async(path:string)=>{const s=await stat(path,{bigint:true});return `${s.size}/${s.mtimeNs}/${s.ino}`}
    for(const path of monitored)stamps.set(path,await stamp(path))
    const snapshotDocument=await readJSON(snapshot)
    for(const name of ['base','delta']){const item=snapshotDocument[name];stamps.set(item.path,await stamp(item.path));monitored.push(item.path)}
    const assertPins=async()=>{for(const path of monitored)if(await stamp(path)!==stamps.get(path))throw Error('Pinned verification input changed');await worker!.sample([])}
    const stopped=async()=>{try{await stat(join(work,'STOP'));return true}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;return false}}
    let stop=false,qualityFailed=false
    const summary=()=>{
      const progress=verificationProgress(proofs,selected.length,selected.reduce((s,r)=>s+r.components,0),sampleOnly,stop)
      const display=proofs.flatMap(p=>p.displayMaximum===null?[]:[p.displayMaximum])
      return {schema:'ngii-national-heights-v1',runSHA256:runSHA,...progress,sampleOnly,samplePassed:proofs.length===selected.length&&proofs.every(p=>p.passed),state:stop?'stopped':qualityFailed?'quality_failed':shard&&done.size===mine.length?'shard-complete':progress.pendingRegions?'waiting-candidates':'complete',buildingCatalogSHA256:hash(canonicalJSON([...pins].sort((a,b)=>a.owner<b.owner?-1:a.owner>b.owner?1:0))),terrainArchiveSHA256:terrainSHA,sourceVrtSHA256:meta.vrt_sha256,sourceFilesSHA256:nativeReady.sourceFilesSHA256,records:proofs.reduce((s,p)=>s+p.buildings,0),missing:0,nativeNoData:proofs.reduce((s,p)=>s+p.nativeNoDataCount,0),nativeEvidence:progress.nativeFinite?'recorded':'insufficient',nativeDisagreement:{gate:'record-only',thresholdMetres:NATIVE_RECORD_THRESHOLD_METRES,maxMetres:display.length?Math.max(...display):null,regionsOver:proofs.filter(p=>p.nativeOver>0).length,buildingsOver:proofs.reduce((s,p)=>s+p.nativeOver,0)},supportedGroundBuildings:proofs.reduce((s,p)=>s+p.supportedGroundBuildings,0),unresolvedGroundBuildings:proofs.reduce((s,p)=>s+p.unresolvedGroundBuildings,0),absoluteErrorMetres:{maximum:display.length?Math.max(...display):null},publishedBuildingDatumCheck:{expected:progress.expectedComponents,compared:progress.compared,maximumAbsoluteErrorMetres:proofs.length?Math.max(...proofs.map(p=>p.datumMaximum)):null},scope:{datum:'Independent pinned resolved archive at canonical anchor vs each stored component',display:'Pinned native DEM finite anchors vs resolved archive, recorded only; native NoData classified separately'},regions:proofs.map(p=>({owner:p.owner,buildings:p.buildings,components:p.components,passed:p.passed,nativeMaximumMetres:p.displayMaximum,nativeOver:p.nativeOver}))}
    }
    await atomic(join(work,`height-verification${tag}.json`),summary())
    while(done.size<mine.length){
      await checkSpace();await assertPins();await discover()
      for(const target of mine){
      if(done.has(target.region14)||!found.has(target.region14))continue
      if(await stopped()){stop=true;break}
      await checkSpace();await assertPins()

      const folder=found.get(target.region14)!,receiptFile=join(folder,'candidate-receipt.json'),receipt=await readJSON(receiptFile),receiptSHA=await fileSHA(receiptFile)
      const expected={schema:'ngii-region-candidate-v1',owner:target.region14,completeRegion:true,sourcePlanSHA256:plan.planSHA256,sourcePlanFileSHA256:planSHA,inventorySHA256:inventorySHA,terrainSHA256:terrainSHA,terrainContract:TERRAIN_HEIGHT_CONTRACT,meshRevision:BUILDING_MESH_REVISION,assetPacking:NGII_ASSET_PACKING,buildings:target.buildings,components:target.components}
      const file=join(work,'regions',target.region14.replaceAll('/','-')+'.json');let previous:any
      try{previous=await readJSON(file)}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e}
      // Merge fast path: a shard already re-hashed these exact files under this run; any stamp change re-hashes.
      const fileStamps=await candidateFileStamps(folder,receipt),fast=stampedReuse(previous,runSHA,receiptSHA,fileStamps)
      if(fast){if(Object.entries(expected).some(([k,v])=>receipt[k]!==v))throw Error('Existing candidate identity mismatch')}
      else {if(!await verifyExistingCandidate(folder,expected))throw Error('Missing candidate');if(canonicalJSON(await candidateFileStamps(folder,receipt))!==canonicalJSON(fileStamps))throw Error('Candidate payload changed during verification')}
      let proof=reusableProof(previous,runSHA,receiptSHA)
      if(proof&&!fast)await atomic(file,{...previous,fileStamps})
      if(!proof){const ground=JSON.parse(gunzipSync(await readFile(join(folder,'ground-source.json.gz'))).toString()),footprints=JSON.parse(gunzipSync(await readFile(join(folder,'footprints.json.gz'))).toString());if(ground.archiveSha256!==terrainSHA||ground.contract!==TERRAIN_HEIGHT_CONTRACT)throw Error('Metadata terrain identity mismatch');proof=await verifyRegion(target.region14,rows(target.region14),ground.buildings,footprints,(lon,lat)=>contract.samplePosition(lon,lat),p=>worker!.sample(p));if(proof.inputSHA256!==receipt.inputSHA256||proof.buildings!==target.buildings||proof.components!==target.components)throw Error('Canonical input/count mismatch');await atomic(file,{runSHA256:runSHA,receiptSHA256:receiptSHA,proofSHA256:hash(canonicalJSON(proof)),proof,fileStamps})}
      if(receipt.supportedGroundBuildings!==proof.supportedGroundBuildings||receipt.unresolvedGroundBuildings!==proof.unresolvedGroundBuildings)throw Error('Ground support counts mismatch')
      pins.push({owner:target.region14,receiptSHA256:receiptSHA,uri:'/api/map-data/world-buildings/'+relative(join(dataRoot,'world-buildings'),folder).replaceAll('\\','/')+'/tileset.json'});proofs.push((({nativeNoData,errors,...compact})=>({...compact,nativeNoDataCount:nativeNoData.length}))(proof));done.add(target.region14)
      await assertPins()
      await atomic(join(work,`progress${tag}.json`),{state:'verifying',pid:process.pid,verifiedRegions:done.size,pendingRegions:mine.length-done.size,lastRegion:target.region14,rssBytes:process.memoryUsage().rss})
      console.log(JSON.stringify({region:target.region14,buildings:proof.buildings,passed:proof.passed,displayMaximum:proof.displayMaximum,nativeOver:proof.nativeOver,resumed:Boolean(previous),payloadRehashed:!fast}))
      // Only the served-terrain datum gate (0.01 m) stops; native disagreement was recorded above.
      if(!proof.passed){qualityFailed=true;break}
      }
      if(await stopped())stop=true
      await assertPins();await checkSpace();await atomic(join(work,`height-verification${tag}.json`),summary())
      if(stop||qualityFailed||done.size===mine.length||!watch)break
      await atomic(join(work,`progress${tag}.json`),{state:'waiting-candidates',pid:process.pid,verifiedRegions:done.size,pendingRegions:mine.length-done.size,pollSeconds,rssBytes:process.memoryUsage().rss})
      await new Promise(r=>setTimeout(r,pollSeconds*1000))
    }
    await worker.close();worker=undefined
    for(const path of monitored)if(await stamp(path)!==stamps.get(path))throw Error('Pinned verification input changed at close')
    const report=summary();await checkSpace();await atomic(join(work,`height-verification${tag}.json`),report)
    await atomic(join(work,`progress${tag}.json`),{state:report.state,pid:process.pid,verifiedRegions:done.size,pendingRegions:report.pendingRegions,rssBytes:process.memoryUsage().rss})
    console.log(JSON.stringify({complete:report.complete,passed:report.passed,samplePassed:report.samplePassed,records:report.records,nativeNoData:report.nativeNoData,pendingRegions:report.pendingRegions,absoluteErrorMetres:report.absoluteErrorMetres,publishedBuildingDatumCheck:report.publishedBuildingDatumCheck,work}));return report
  } catch(error){await atomic(join(work,`progress${tag}.json`),{state:String(error).includes('needs_storage')?'needs_storage':'failed',pid:process.pid,error:String(error)});throw error
  } finally {worker?.stop();if(db){db.exec('ROLLBACK');db.close()}await local?.close();await unlink(lock)}
}
if(import.meta.main)main().then(r=>{if(r.state!=='shard-complete'&&!r.samplePassed)process.exitCode=1}).catch(e=>{console.error(String(e));process.exitCode=1})
