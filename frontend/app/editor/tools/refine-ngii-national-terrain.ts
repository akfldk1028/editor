/** Adaptive candidate only: canonical anchors -> bounded native batches -> missing detail tiles. */
import {Database} from 'bun:sqlite'
import {createHash} from 'node:crypto'
import {createReadStream} from 'node:fs'
import {mkdir,readFile,writeFile,rename,unlink,stat,statfs} from 'node:fs/promises'
import {resolve,join,relative,isAbsolute} from 'node:path'
import {fileURLToPath} from 'node:url'
import {inflateSync,gzipSync,gunzipSync} from 'node:zlib'
import {spawnSync} from 'node:child_process'
import {PMTiles,zxyToTileId} from 'pmtiles'
import {openCanonicalSnapshot,type CanonicalPlan,type CanonicalRegionInventory} from './ngii-canonical-source'
import {NativeWorker,canonicalJSON,validateCompletedInventoryPin} from './verify-ngii-national-heights'
import {openLocalArchive} from './local-building-archive'
import {decodeHeightTile} from '../features/world/lib/terrain-archive'
import {createTerrainHeightContract,TERRAIN_HEIGHT_CONTRACT,type TerrainGridKey} from '../features/world/lib/terrain-height-contract'
import {selectRegions} from './bake-ngii-region'
export type Anchor={id:string;point:[number,number];native:number|null}
type Sample={height:number;sourceLevels:number[];ellipsoidZero:boolean}
const hash=(b:string|Uint8Array)=>createHash('sha256').update(b).digest('hex')
const fileSHA=async(p:string)=>{const h=createHash('sha256');for await(const b of createReadStream(p))h.update(b);return h.digest('hex')}
const json=async(p:string)=>JSON.parse(await readFile(p,'utf8'))
const atomic=async(p:string,v:unknown)=>{await writeFile(p+'.part',JSON.stringify(v,null,2));await rename(p+'.part',p)}
const keyFor=(point:[number,number],level:number):TerrainGridKey=>{const width=180/2**level;return{level,x:Math.floor((point[0]+180)/width),y:Math.floor((90-point[1])/width)}}
export function validateSeedIdentity(old:any,current:any){
 for(const key of ['sourcePins','baseReceiptSHA256','contract','sourcePlanSHA256'])if(canonicalJSON(old[key])!==canonicalJSON(current[key]))throw Error('Seed source pin mismatch: '+key)
}
export function verifySeedTile(row:{id:number;level:number;x:number;y:number;data:Uint8Array;decoded_sha256:string},nativeRaw:Uint8Array){
 if(row.level<16||row.level>20||zxyToTileId(row.level+1,row.x,row.y)!==row.id)throw Error('Invalid seed tile key')
 const decoded=gunzipSync(row.data)
 if(hash(decoded)!==row.decoded_sha256||!decoded.equals(Buffer.from(nativeRaw)))throw Error('Seed native decoded bytes mismatch')
 return row.data
}
export function assertPassedResumeReceipt(receipt:string){const r=JSON.parse(receipt);if(r.passed!==true)throw Error('Previous refinement failed; review required');return r}
export async function refineAnchors(anchors:Anchor[],api:{sample:(p:[number,number])=>Promise<Sample>;exists:(k:TerrainGridKey)=>Promise<boolean>;add:(k:TerrainGridKey)=>Promise<void>;reset:()=>void},maxLevel=20){
 const check=async()=>{const errors:{id:string;point:[number,number];native:number;height:number;error:number;sourceLevels:number[]}[]=[];let max=0,supported=0,unresolved=0,nativeNoData=0;for(const a of anchors){const s=await api.sample(a.point);if(!Number.isFinite(s.height))throw Error('Invalid resolved height');s.ellipsoidZero?unresolved++:supported++;if(a.native===null){nativeNoData++;continue}const error=Math.abs(s.height-a.native);max=Math.max(max,error);if(error>.5)errors.push({id:a.id,point:a.point,native:a.native,height:s.height,error,sourceLevels:s.sourceLevels})}return{errors,maximum:max,supported,unresolved,nativeNoData}}
 const initial=await check();let current=initial,added=0
 for(let level=16;level<=maxLevel&&current.errors.length;level++){
  const keys=new Map<number,TerrainGridKey>()
  for(const e of current.errors){if(e.sourceLevels.length>0&&e.sourceLevels.every(l=>l>=level))continue;const k=keyFor(e.point,level);keys.set(zxyToTileId(level+1,k.x,k.y),k)}
  for(const[,k]of [...keys].sort(([a],[b])=>a-b))if(!await api.exists(k)){await api.add(k);added++}
  api.reset();current=await check() // Recheck ALL region anchors, including previously passing neighbours.
 }
 return{initial,current,added,passed:current.errors.length===0}
}

export async function main(args=process.argv.slice(2)){
 const opt=(k:string)=>{const i=args.indexOf(k);if(i<0||!args[i+1])throw Error('Missing '+k);return args[i+1]!}
 const seedPath=args.includes('--seed-overlay')?resolve(opt('--seed-overlay')):undefined
 const root=resolve(opt('--data-root')),work=resolve(opt('--work')),snapshot=resolve(opt('--snapshot')),planPath=resolve(opt('--plan')),regionsPath=resolve(opt('--regions')),queuePath=resolve(opt('--queue-inputs')),basePath=resolve(opt('--base')),receiptPath=resolve(opt('--base-receipt')),dem=resolve(opt('--dem')),python=opt('--python')
 const rel=relative(root,work),protectedPaths=[basePath,receiptPath,dem,snapshot,planPath,regionsPath,queuePath,...(seedPath?[seedPath]:[])]
 if(!rel||rel.startsWith('..')||isAbsolute(rel)||protectedPaths.some(p=>work===p||work===resolve(p,'..')))throw Error('Candidate aliases source/public directory')
 const threads={...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1',MKL_NUM_THREADS:'1',GDAL_CACHEMAX:'64'}
 const verifier=fileURLToPath(new URL('../../../../infra/data/ngii_canonical_snapshot.py',import.meta.url))
 const gate=spawnSync(python,['-X','utf8',verifier,'verify','--snapshot',snapshot,'--plan',planPath],{env:threads,windowsHide:true,encoding:'utf8'})
 if(gate.error||gate.status!==0)throw Error('Canonical completed-source gate failed')
 const plan=await json(planPath) as CanonicalPlan,inventory=await json(regionsPath) as CanonicalRegionInventory,baseReceipt=await json(receiptPath),queue=await json(queuePath)
 const sourcePins={snapshotSHA256:await fileSHA(snapshot),planFileSHA256:await fileSHA(planPath),terrainSHA256:await fileSHA(basePath),terrainPath:basePath,regionsPath,regionsSHA256:await fileSHA(regionsPath)}
 validateCompletedInventoryPin(queue,sourcePins,plan,inventory)
 if(sourcePins.terrainSHA256!==baseReceipt.sha256)throw Error('Base archive SHA mismatch')
 const selected=selectRegions(inventory.regions,args.includes('--region')?opt('--region'):undefined,args.includes('--sample-regions')?Number(opt('--sample-regions')):undefined),sampleOnly=args.includes('--region')||args.includes('--sample-regions')
 const workerPath=fileURLToPath(new URL('./ngii-native-height-worker.py',import.meta.url))
 const bridgePath=fileURLToPath(new URL('./verify-ngii-national-heights.ts',import.meta.url)),canonicalReaderPath=fileURLToPath(new URL('./ngii-canonical-source.ts',import.meta.url))
 const noSeedWal=async()=>{if(seedPath)try{if((await stat(seedPath+'-wal')).size)throw Error('Seed WAL is not empty')}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e}}
 await noSeedWal();let seedFingerprint:any,seedIdentity:any
 if(seedPath){const before=await stat(seedPath,{bigint:true});const seed=new Database(seedPath,{readonly:true});try{seedIdentity=JSON.parse((seed.query("SELECT value FROM metadata WHERE key='identity'").get() as any).value)}finally{seed.close()}seedFingerprint={path:seedPath,sha256:await fileSHA(seedPath),identitySHA256:hash(canonicalJSON(seedIdentity)),bytes:before.size.toString(),mtimeNs:before.mtimeNs.toString()};const after=await stat(seedPath,{bigint:true});if(after.size!==before.size||after.mtimeNs!==before.mtimeNs)throw Error('Seed changed during pinning');await noSeedWal()}
 const identity={seed:seedFingerprint??null,nativeStampPolicy:{seconds:1,emptyHeartbeat:'force',fullFingerprintSeconds:60},nativeBridgeSHA256:await fileSHA(bridgePath),canonicalReaderSHA256:await fileSHA(canonicalReaderPath),schema:'ngii-adaptive-refinement-v1',recipe:'native-anchor-adaptive-grid-v1',sourcePins,baseReceiptSHA256:await fileSHA(receiptPath),contract:TERRAIN_HEIGHT_CONTRACT,sourcePlanSHA256:plan.planSHA256,sampleOnly,selected:selected.map(r=>r.region14),codeSHA256:await fileSHA(fileURLToPath(import.meta.url)),contractCodeSHA256:await fileSHA(fileURLToPath(new URL('../features/world/lib/terrain-height-contract.ts',import.meta.url))),nativeWorkerSHA256:await fileSHA(workerPath),nativeSourceReaderSHA256:await fileSHA(fileURLToPath(new URL('./incremental_terrain_archive.py',import.meta.url)))}
 if(seedIdentity)validateSeedIdentity(seedIdentity,identity)
 await mkdir(work,{recursive:true});const space=async(extra=0)=>{const s=await statfs(work);if(s.bavail*s.bsize<20*1024**3+extra)throw Error('needs_storage: 20GiB reserve')};await space()
 const lock=join(work,'refinement.lock');await writeFile(lock,String(process.pid),{flag:'wx'})
 let canonical:Database|undefined,overlay:Database|undefined,local:Awaited<ReturnType<typeof openLocalArchive>>|undefined,worker:NativeWorker|undefined
 try{
  const pin=join(work,'inputs.json');try{if(canonicalJSON(await json(pin))!==canonicalJSON(identity))throw Error('Candidate recipe/source pin changed')}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;await writeFile(pin,JSON.stringify(identity,null,2),{flag:'wx'})}
  const overlayPath=join(work,'refinement-spool.sqlite')
  // A pre-existing database is accepted only after its identity has been checked read-only.
  try{await stat(overlayPath);const prior=new Database(overlayPath,{readonly:true});try{if((prior.query("SELECT value FROM metadata WHERE key='identity'").get() as any)?.value!==canonicalJSON(identity))throw Error('Unowned overlay')}finally{prior.close()}}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e}
  overlay=new Database(overlayPath);overlay.exec('PRAGMA journal_mode=WAL; PRAGMA cache_size=-4096; CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS tiles(id INTEGER PRIMARY KEY,level INTEGER NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,data BLOB NOT NULL,decoded_sha256 TEXT NOT NULL); CREATE TABLE IF NOT EXISTS regions(owner TEXT PRIMARY KEY,receipt TEXT NOT NULL);')
  overlay.query("INSERT OR IGNORE INTO metadata VALUES('identity',?)").run(canonicalJSON(identity))
  canonical=openCanonicalSnapshot(snapshot);canonical.exec('PRAGMA query_only=ON; BEGIN')
  const sourceQuery=canonical.query<{id:string;payload:Uint8Array},[string]>('SELECT id,payload FROM buildings WHERE region14=? ORDER BY region16,id')
  local=await openLocalArchive(basePath);const base=new PMTiles(local),meta=await base.getMetadata() as any
  if(meta.schema!=='ngii-heightmap-v1'||meta.maxLevel!==20||meta.size!==33||meta.archiveZoomOffset!==1)throw Error('Unsupported base archive')
  const workerArgs=['-X','utf8',workerPath,'--stamp-seconds','1','--vrt',dem,'--source-vrt-sha256',meta.vrt_sha256,'--source-files-sha256',meta.sourceFilesSHA256,'--recursive-source-files-sha256',meta.recursiveSourceFilesSHA256]
  worker=new NativeWorker(python,workerArgs,args.includes('--below-normal'));const native=await worker.start()
  const monitored=[...protectedPaths,fileURLToPath(import.meta.url),workerPath,bridgePath,canonicalReaderPath,fileURLToPath(new URL('../features/world/lib/terrain-height-contract.ts',import.meta.url))],stamps=new Map<string,string>(),snap=await json(snapshot)
  for(const n of ['base','delta'])monitored.push(snap[n].path)
  const stamp=async(p:string)=>{const s=await stat(p,{bigint:true});return `${s.size}/${s.mtimeNs}/${s.ino}`}
  for(const p of monitored)stamps.set(p,await stamp(p))
  const unchanged=async()=>{await noSeedWal();for(const p of monitored)if(await stamp(p)!==stamps.get(p))throw Error('Pinned refinement source changed');await worker!.sample([])}
  const stop=async()=>{try{await stat(join(work,'STOP'));return true}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;return false}}
  const tileQuery=overlay.query<{data:Uint8Array},[number]>('SELECT data FROM tiles WHERE id=?')
  const makeContract=()=>createTerrainHeightContract(async({level,x,y})=>{const row=tileQuery.get(zxyToTileId(level+1,x,y));if(row){const b=gunzipSync(row.data);return decodeHeightTile(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength))}const t=await base.getZxy(level+1,x,y);return t?decodeHeightTile(t.data):null},{archiveSha256:baseReceipt.sha256,minLevel:meta.minLevel,maxLevel:20,keep:128})
  let contract=makeContract()
  const anchors=async(owner:string,expected:number,components:number)=>{const result:Anchor[]=[];let partCount=0,batch:{id:string;point:[number,number]}[]=[]
   const flush=async()=>{const heights=await worker!.sample(batch.map(r=>r.point));if(heights.length!==batch.length||heights.some(v=>v!==null&&!Number.isFinite(v)))throw Error('Invalid native response');for(let i=0;i<batch.length;i++)result.push({...batch[i]!,native:heights[i]!});batch=[]}
   for(const stored of sourceQuery.iterate(owner)){const r=JSON.parse(inflateSync(stored.payload).toString()),source=plan.sources.find(s=>s.id===r.provenance.sourceId);if(r.canonicalBuildingId!==stored.id||!source||!Number.isInteger(r.provenance.row)||r.provenance.row<0||r.provenance.row>=source.expectedRows)throw Error('Canonical source identity mismatch');partCount+=r.geomWGS84.type==='Polygon'?1:r.geomWGS84.coordinates.length;batch.push({id:stored.id,point:r.anchorWGS84});if(batch.length===256)await flush()}
   if(batch.length)await flush();if(result.length!==expected||partCount!==components)throw Error('Canonical regional count mismatch');return result}
  const nativeTile=async(k:TerrainGridKey)=>{
   const width=180/2**k.level,points:number[][]=[];for(let row=0;row<33;row++)for(let col=0;col<33;col++)points.push([-180+(k.x+col/32)*width,90-(k.y+row/32)*width]);const heights=await worker!.sample(points);if(heights.length!==1089||heights.some(v=>v!==null&&(!Number.isFinite(v)||v< -500||v>9000)))throw Error('Invalid native detail grid')
   const raw=Buffer.alloc(8+1089*4);raw.write('HTM1');raw.writeUInt16LE(33,4);for(let i=0;i<1089;i++)raw.writeFloatLE(heights[i]===null?NaN:heights[i]!,8+i*4);return raw
  }
  if(seedPath){
   const seed=new Database(seedPath,{readonly:true});let checked=0,bytes=0;const started=performance.now()
   try{
    for(const row of seed.query<any,[]>('SELECT id,level,x,y,data,decoded_sha256 FROM tiles ORDER BY id').iterate()){
     if(checked%32===0){await unchanged();await space(262144);if(await stop()){await atomic(join(work,'progress.json'),{state:'stopped-seed',checkedSeedTiles:checked});return}}
     if(await base.getZxy(row.level+1,row.x,row.y))throw Error('Seed overwrites immutable base tile')
     const raw=await nativeTile(row),data=verifySeedTile(row,raw),existing=tileQuery.get(row.id)
     if(existing&&!Buffer.from(existing.data).equals(Buffer.from(data)))throw Error('Existing overlay seed bytes differ')
     if(!existing)overlay.query('INSERT INTO tiles VALUES(?,?,?,?,?,?)').run(row.id,row.level,row.x,row.y,data,row.decoded_sha256)
     checked++;bytes+=data.length
     if(checked%32===0)await atomic(join(work,'progress.json'),{state:'verifying-seed',checkedSeedTiles:checked,seedBytes:bytes,elapsedSeconds:(performance.now()-started)/1000,rssBytes:process.memoryUsage().rss})
    }
    await unchanged();overlay.query("INSERT OR REPLACE INTO metadata VALUES('seedVerification',?)").run(JSON.stringify({checked,bytes,elapsedSeconds:(performance.now()-started)/1000,fingerprint:seedFingerprint}));contract=makeContract()
   }finally{seed.close()}
  }
  const api={sample:(p:[number,number])=>contract.samplePosition(...p),exists:async(k:TerrainGridKey)=>Boolean(tileQuery.get(zxyToTileId(k.level+1,k.x,k.y))||await base.getZxy(k.level+1,k.x,k.y)),reset:()=>{contract=makeContract()},add:async(k:TerrainGridKey)=>{
   await space(8192);const raw=await nativeTile(k),bytes=gzipSync(raw,{level:1});overlay!.query('INSERT INTO tiles VALUES(?,?,?,?,?,?)').run(zxyToTileId(k.level+1,k.x,k.y),k.level,k.x,k.y,bytes,hash(raw))}}
  let verified=0,nativeFinite=0,nativeNoData=0,maximum=0
  for(const region of selected){await space();await unchanged();if(await stop()){await atomic(join(work,'progress.json'),{state:'stopped',verifiedRegions:verified,pendingRegions:selected.length-verified});return}
   const previous=overlay.query<{receipt:string},[string]>('SELECT receipt FROM regions WHERE owner=?').get(region.region14)
   if(previous){assertPassedResumeReceipt(previous.receipt);verified++;continue}
   const points=await anchors(region.region14,region.buildings,region.components);overlay.exec('BEGIN IMMEDIATE')
   try{const proof=await refineAnchors(points,api);await unchanged();overlay.query('INSERT INTO regions VALUES(?,?)').run(region.region14,JSON.stringify({owner:region.region14,...proof,buildings:points.length}));overlay.exec('COMMIT');if(!proof.passed){await atomic(join(work,'failed-region.json'),{owner:region.region14,...proof});throw Error('Refinement still exceeds0.5m at maximum level')}}catch(e){try{overlay.exec('ROLLBACK')}catch{}throw e}
   verified++;await atomic(join(work,'progress.json'),{state:'refining',verifiedRegions:verified,pendingRegions:selected.length-verified,rssBytes:process.memoryUsage().rss});console.log(JSON.stringify({region:region.region14,verifiedRegions:verified}))
  }
  // Final receipts apply only to this exact immutable overlay generation.
  overlay.exec('CREATE TABLE IF NOT EXISTS final_checks(owner TEXT PRIMARY KEY,receipt TEXT NOT NULL)')
  const generation=JSON.stringify(overlay.query('SELECT count(*) AS n,coalesce(max(id),0) AS last FROM tiles').get())
  const oldGeneration=(overlay.query("SELECT value FROM metadata WHERE key='finalGeneration'").get() as any)?.value
  if(oldGeneration!==generation){overlay.exec('DELETE FROM final_checks');overlay.query("INSERT OR REPLACE INTO metadata VALUES('finalGeneration',?)").run(generation)}
  // A later region's newly inserted tile can affect an earlier neighbour. Never publish from first-pass receipts.
  for(const region of selected){await space();await unchanged();if(await stop()){await atomic(join(work,'progress.json'),{state:'stopped-final-check',region:region.region14});return}const done=overlay.query<{receipt:string},[string]>('SELECT receipt FROM final_checks WHERE owner=?').get(region.region14);if(done){const r=JSON.parse(done.receipt);nativeFinite+=r.nativeFinite;nativeNoData+=r.nativeNoData;maximum=Math.max(maximum,r.maximum);continue}const beforeFinite=nativeFinite,beforeNoData=nativeNoData;let regionMaximum=0;const points=await anchors(region.region14,region.buildings,region.components),failures=[];for(const a of points){const s=await contract.samplePosition(...a.point);if(a.native===null){nativeNoData++;continue}nativeFinite++;const error=Math.abs(s.height-a.native);maximum=Math.max(maximum,error);regionMaximum=Math.max(regionMaximum,error);if(error>.5)failures.push({id:a.id,point:a.point,native:a.native,height:s.height,error})}if(failures.length){await atomic(join(work,'failed-neighbour-check.json'),{region:region.region14,failures});throw Error('Neighbour/final validation exceeds0.5m; candidate not publishable')}await unchanged();overlay.query('INSERT INTO final_checks VALUES(?,?)').run(region.region14,JSON.stringify({nativeFinite:nativeFinite-beforeFinite,nativeNoData:nativeNoData-beforeNoData,maximum:regionMaximum}));await atomic(join(work,'progress.json'),{state:'final-check',verifiedRegions:verified,checkedRegions:(overlay.query('SELECT count(*) AS n FROM final_checks').get() as any).n,rssBytes:process.memoryUsage().rss})}
  await unchanged();await worker.close();worker=undefined
  const tileTotals=overlay.query('SELECT count(*) AS tiles,coalesce(sum(length(data)),0) AS bytes FROM tiles').get()
  const report={schema:'ngii-adaptive-refinement-proof-v1',complete:!sampleOnly,sampleOnly,publishable:false,passed:nativeFinite>0,regions:verified,expectedRegions:inventory.regionCount,nativeFinite,nativeNoData,maximumAbsoluteErrorMetres:maximum,baseArchiveSHA256:baseReceipt.sha256,sourceFingerprint:native,identitySHA256:hash(canonicalJSON(identity)),added:tileTotals,finalNeighbourCheck:true,independentPackedArchiveVerificationRequired:true}
  overlay.query("INSERT OR REPLACE INTO metadata VALUES('verification',?)").run(JSON.stringify(report));overlay.exec('PRAGMA wal_checkpoint(TRUNCATE)');await atomic(join(work,'refinement-verification.json'),report);await atomic(join(work,'progress.json'),{state:sampleOnly?'sample-complete':'ready-to-pack',...report});console.log(JSON.stringify(report));return report
 }catch(e){await atomic(join(work,'progress.json'),{state:String(e).includes('needs_storage')?'needs_storage':'failed',error:String(e)});throw e}
 finally{worker?.stop();if(canonical){canonical.exec('ROLLBACK');canonical.close()}overlay?.close();await local?.close();await unlink(lock)}
}
if(import.meta.main)main().catch(e=>{console.error(String(e));process.exitCode=1})

