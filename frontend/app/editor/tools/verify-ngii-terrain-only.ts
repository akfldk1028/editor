/** Independent packed-archive gate before mesh baking; never substitutes for final mesh datum proof. */
import {createHash} from 'node:crypto'
import {createReadStream} from 'node:fs'
import {mkdir,readFile,writeFile,rename,unlink,stat,statfs} from 'node:fs/promises'
import {resolve,join,relative,isAbsolute} from 'node:path'
import {fileURLToPath} from 'node:url'
import {inflateSync} from 'node:zlib'
import {spawnSync} from 'node:child_process'
import {PMTiles} from 'pmtiles'
import {openCanonicalSnapshot,type CanonicalPlan,type CanonicalRegionInventory} from './ngii-canonical-source'
import {NativeWorker,canonicalJSON,validateCompletedInventoryPin} from './verify-ngii-national-heights'
import {openLocalArchive} from './local-building-archive'
import {decodeHeightTile} from '../features/world/lib/terrain-archive'
import {createTerrainHeightContract,TERRAIN_HEIGHT_CONTRACT} from '../features/world/lib/terrain-height-contract'
import type {TerrainSample} from './ngii-mesh-input'

type Anchor={id:string;point:number[]}
type Proof={records:number;nativeFinite:number;nativeNoData:{id:string;classification:string}[];maximum:number|null;errors:{id:string;error:number}[];passed:boolean}
const hash=(b:string|Uint8Array)=>createHash('sha256').update(b).digest('hex')
const fileSHA=async(p:string)=>{const h=createHash('sha256');for await(const b of createReadStream(p))h.update(b);return h.digest('hex')}
const json=async(p:string)=>JSON.parse(await readFile(p,'utf8'))
const atomic=async(p:string,v:unknown)=>{await writeFile(p+'.part',JSON.stringify(v,null,2));await rename(p+'.part',p)}
export function validateTerrainReceipt(meta:any,receipt:any,actualSHA:string){
 if(!/^[a-f0-9]{64}$/.test(actualSHA)||receipt.sha256!==actualSHA||meta.schema!=='ngii-heightmap-v1'||meta.size!==33||meta.archiveZoomOffset!==1||meta.grid!=='Cesium.GeographicTilingScheme')throw Error('Invalid terrain archive receipt')
 for(const key of ['vrt_sha256','sourceFilesSHA256','recursiveSourceFilesSHA256']){
  if(key==='recursiveSourceFilesSHA256'&&meta[key]===undefined&&receipt.metadata?.[key]===undefined)continue
  if(!/^[a-f0-9]{64}$/.test(meta[key]??'')||receipt.metadata?.[key]!==meta[key])throw Error('Terrain source fingerprint mismatch')
 }
 if(receipt.vrt_sha256!==meta.vrt_sha256)throw Error('Terrain VRT receipt mismatch')
}
export async function verifyTerrainAnchors(rows:Iterable<Anchor>,sample:(lon:number,lat:number)=>Promise<TerrainSample>,native:(points:number[][])=>Promise<(number|null)[]>,batchSize=256):Promise<Proof>{
 if(!Number.isInteger(batchSize)||batchSize<1||batchSize>4096)throw Error('Invalid batch size')
 const proof:Proof={records:0,nativeFinite:0,nativeNoData:[],maximum:null,errors:[],passed:true};let batch:Anchor[]=[]
 const consume=async()=>{
  const heights=await native(batch.map(r=>r.point))
  if(heights.length!==batch.length||heights.some(v=>v!==null&&(typeof v!=='number'||!Number.isFinite(v))))throw Error('Invalid native response')
  for(let i=0;i<batch.length;i++){
   const r=batch[i]!,s=await sample(r.point[0]!,r.point[1]!)
   if(!Number.isFinite(s.height)||s.contract!==TERRAIN_HEIGHT_CONTRACT||!s.sourceLevels.length||s.ellipsoidZero!==s.sourceLevels.includes(-1)||!s.sourceLevels.every(l=>Number.isInteger(l)&&l>=-1&&l<=20))throw Error('Invalid terrain policy')
   const h=heights[i]!
   if(h===null)proof.nativeNoData.push({id:r.id,classification:s.ellipsoidZero?'declared-ellipsoid-zero':'ancestor-supported'})
   else{const error=Math.abs(s.height-h);proof.nativeFinite++;proof.maximum=Math.max(proof.maximum??0,error);if(error>.5)proof.errors.push({id:r.id,error})}
   proof.records++
  }
  batch=[]
 }
 for(const r of rows){if(!r.id||r.point.length!==2||!r.point.every(Number.isFinite)||Math.abs(r.point[0]!)>180||Math.abs(r.point[1]!)>90)throw Error('Invalid canonical anchor');batch.push(r);if(batch.length>=batchSize)await consume()}
 if(batch.length)await consume();proof.passed=proof.errors.length===0;return proof
}
export function terrainOnlySummary(proofs:Pick<Proof,'records'|'nativeFinite'|'passed'>[],regions:number,records:number,sampleOnly:boolean){
 const compared=proofs.reduce((n,p)=>n+p.records,0),nativeFinite=proofs.reduce((n,p)=>n+p.nativeFinite,0)
 if(proofs.length>regions||compared>records)throw Error('Inventory count exceeded')
 const complete=!sampleOnly&&proofs.length===regions&&compared===records
 const samplePassed=proofs.length===regions&&compared===records&&nativeFinite>0&&proofs.every(p=>p.passed)
 return{complete,sampleOnly,samplePassed,passed:complete&&samplePassed,compared,nativeFinite,pendingRegions:regions-proofs.length}
}
export async function main(args=process.argv.slice(2)){
 const option=(k:string)=>{const i=args.indexOf(k);if(i<0||!args[i+1])throw Error('Missing '+k);return args[i+1]!}
 const root=resolve(option('--data-root')),work=resolve(option('--work')),snapshot=resolve(option('--snapshot')),planPath=resolve(option('--plan')),regions=resolve(option('--regions')),pinPath=resolve(option('--queue-inputs')),terrain=resolve(option('--terrain')),receiptPath=resolve(option('--terrain-receipt')),dem=resolve(option('--dem')),python=option('--python')
 const rel=relative(root,work);if(!rel||rel.startsWith('..')||isAbsolute(rel))throw Error('Evidence work must be below DATA_ROOT')
 const protectedFiles=[snapshot,planPath,regions,pinPath,terrain,receiptPath,dem];if(protectedFiles.some(p=>p===work||relative(work,p)===''||!relative(work,p).startsWith('..')&&!isAbsolute(relative(work,p))))throw Error('Evidence work aliases input')
 await mkdir(work,{recursive:true});const lock=join(work,'verification.lock');await writeFile(lock,JSON.stringify({pid:process.pid}),{flag:'wx'})
 let local:Awaited<ReturnType<typeof openLocalArchive>>|undefined,worker:NativeWorker|undefined,db:ReturnType<typeof openCanonicalSnapshot>|undefined
 try{
  const plan=await json(planPath) as CanonicalPlan,inventory=await json(regions) as CanonicalRegionInventory,receipt=await json(receiptPath),snapshotDoc=await json(snapshot)
  const sourceBindings={snapshotSHA256:await fileSHA(snapshot),planFileSHA256:await fileSHA(planPath),regionsPath:regions,regionsSHA256:await fileSHA(regions)}
  validateCompletedInventoryPin(await json(pinPath),sourceBindings,plan,inventory)
  const gate=spawnSync(python,['-X','utf8',fileURLToPath(new URL('../../../../infra/data/ngii_canonical_snapshot.py',import.meta.url)),'verify','--snapshot',snapshot,'--plan',planPath],{encoding:'utf8',windowsHide:true,env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1',MKL_NUM_THREADS:'1'}})
  if(gate.status!==0||gate.error)throw Error('Completed source snapshot gate failed')
  const terrainSHA=await fileSHA(terrain);local=await openLocalArchive(terrain);const archive=new PMTiles(local),meta=await archive.getMetadata() as any;validateTerrainReceipt(meta,receipt,terrainSHA)
  const region=args.includes('--region')?option('--region'):undefined,selected=inventory.regions.filter(r=>!region||r.region14===region);if(!selected.length)throw Error('Unknown region')
  const codePaths=['./verify-ngii-terrain-only.ts','./verify-ngii-national-heights.ts','./ngii-canonical-source.ts','./ngii-native-height-worker.py','./incremental_terrain_archive.py','../features/world/lib/terrain-height-contract.ts'].map(p=>fileURLToPath(new URL(p,import.meta.url)))
  const identity={schema:'ngii-terrain-only-v1',sourceBindings,terrainSHA256:terrainSHA,receiptSHA256:await fileSHA(receiptPath),queueInputsSHA256:await fileSHA(pinPath),sourceVrtSHA256:meta.vrt_sha256,selected:selected.map(r=>r.region14),codeSHA256:await Promise.all(codePaths.map(fileSHA))},runSHA=hash(canonicalJSON(identity)),identityPath=join(work,'inputs.json')
  try{if(canonicalJSON(await json(identityPath))!==canonicalJSON(identity))throw Error('Verification identity changed')}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;await writeFile(identityPath,JSON.stringify(identity,null,2),{flag:'wx'})}
  const tracked=[...protectedFiles,...codePaths,snapshotDoc.base.path,snapshotDoc.delta.path],stamp=async(p:string)=>{const s=await stat(p,{bigint:true});return `${s.size}/${s.mtimeNs}/${s.ino}`},stamps=await Promise.all(tracked.map(stamp))
  const check=async()=>{for(let i=0;i<tracked.length;i++)if(await stamp(tracked[i]!)!==stamps[i])throw Error('Pinned input changed');if(worker)await worker.sample([]);const s=await statfs(work);if(s.bavail*s.bsize<20*1024**3)throw Error('20GiB reserve')}
  const workerArgs=['-X','utf8',codePaths[3]!,'--vrt',dem,'--source-vrt-sha256',meta.vrt_sha256,'--source-files-sha256',meta.sourceFilesSHA256];if(meta.recursiveSourceFilesSHA256)workerArgs.push('--recursive-source-files-sha256',meta.recursiveSourceFilesSHA256)
  worker=new NativeWorker(python,workerArgs,args.includes('--below-normal'));const ready=await worker.start()
  const contract=createTerrainHeightContract(async({level,x,y})=>{const t=await archive.getZxy(level+1,x,y);return t?decodeHeightTile(t.data):null},{archiveSha256:terrainSHA,minLevel:meta.minLevel,maxLevel:meta.maxLevel,keep:128})
  db=openCanonicalSnapshot(snapshot);db.exec('PRAGMA query_only=ON; BEGIN');const query=db.query<{id:string;payload:Uint8Array},[string]>('SELECT id,payload FROM buildings WHERE region14=? ORDER BY region16,id')
  const proofs:{owner:string;records:number;nativeFinite:number;nativeNoData:number;maximum:number|null;passed:boolean}[]=[];await mkdir(join(work,'regions'),{recursive:true})
  const summary=()=>({...terrainOnlySummary(proofs,selected.length,selected.reduce((s,r)=>s+r.buildings,0),Boolean(region)),schema:'ngii-terrain-only-v1',runSHA256:runSHA,terrainArchiveSHA256:terrainSHA,sourceVrtSHA256:ready.sourceVrtSHA256,sourceFilesSHA256:ready.sourceFilesSHA256,recursiveSourceFilesSHA256:ready.recursiveSourceFilesSHA256,maximumAbsoluteErrorMetres:Math.max(0,...proofs.map(p=>p.maximum??0)),nativeNoData:proofs.reduce((s,p)=>s+p.nativeNoData,0),meshDatumVerified:false,geographicCoverageVerified:false,regions:proofs})
  for(const target of selected){
   await check();try{await stat(join(work,'STOP'));break}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e}
   const path=join(work,'regions',target.region14.replaceAll('/','-')+'.json');let proof:Proof|undefined
   try{const old=await json(path);if(old.runSHA256!==runSHA||old.owner!==target.region14||old.proofSHA256!==hash(canonicalJSON(old.proof)))throw Error('Region proof changed');proof=old.proof}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e}
   if(!proof){let components=0;const rows=function*(){for(const stored of query.iterate(target.region14)){const r=JSON.parse(inflateSync(stored.payload).toString()),ref=r.provenance,source=plan.sources.find(s=>s.id===ref.sourceId);if(r.canonicalBuildingId!==stored.id||!source||!Number.isInteger(ref.row)||ref.row<0||ref.row>=source.expectedRows)throw Error('Canonical provenance mismatch');components+=r.geomWGS84.type==='Polygon'?1:r.geomWGS84.coordinates.length;yield{id:stored.id,point:r.anchorWGS84}}};proof=await verifyTerrainAnchors(rows(),(lon,lat)=>contract.samplePosition(lon,lat),points=>worker!.sample(points));if(proof.records!==target.buildings||components!==target.components)throw Error('Canonical region count mismatch');await check();await atomic(path,{runSHA256:runSHA,owner:target.region14,proofSHA256:hash(canonicalJSON(proof)),proof})}
   if(proof.records!==target.buildings)throw Error('Checkpoint region count mismatch')
   proofs.push({owner:target.region14,records:proof.records,nativeFinite:proof.nativeFinite,nativeNoData:proof.nativeNoData.length,maximum:proof.maximum,passed:proof.passed});await atomic(join(work,'terrain-only-verification.json'),summary());console.log(JSON.stringify({region:target.region14,verifiedRegions:proofs.length,passed:proof.passed}))
   if(!proof.passed)throw Error('Native display exceeds0.5m; no bake approval')
  }
  await check();await worker.close();worker=undefined;const result=summary();await atomic(join(work,'terrain-only-verification.json'),result);if(!result.sampleOnly&&!result.passed)throw Error('Full terrain verification incomplete or insufficient');return result
 }finally{worker?.stop();db?.close();await local?.close();await unlink(lock)}
}
if(import.meta.main)main().then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e);process.exitCode=1})
