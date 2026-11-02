import { readFile, writeFile, rename, statfs, symlink, realpath, unlink } from 'node:fs/promises'
import { join, resolve, dirname } from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { PMTiles } from 'pmtiles'
import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { decodeBuildings, type Footprint } from '../features/world/lib/building-geometry'
import { bakeMesh, frame, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { reconcilePublishedGeometry } from './reconcile-building-geometry'
import { createUnpublishedRegionFolder, groupBuildingRegions, readRegionFilter, regionAssetsComplete } from './building-publication-safety'
import { openLocalArchive } from './local-building-archive'

type Options = { catalogRoot:string; assetRoot:string; regionKeys:Set<string>; limit:number; resume:boolean; minFreeBytes:number; decodeRegion:(x:number,y:number)=>Promise<Footprint[]> }
const sha = (bytes: string | Uint8Array) => createHash('sha256').update(bytes).digest('hex')
const identity = (features: Footprint[]) => sha(JSON.stringify(features.map(f => [f.key, f.pnu, f.ring, f.z, f.h, f.s])))
const atomicJson = async (path: string, value: unknown) => {
  const temporary = `${path}.${randomUUID()}.tmp`
  await writeFile(temporary, JSON.stringify(value), { flag: 'wx' })
  for (let attempt = 0; attempt < 50; attempt++) {
    try { await rename(temporary, path); return }
    catch (error: any) {
      if ((error?.code !== 'EPERM' && error?.code !== 'EACCES' && error?.code !== 'EBUSY') || attempt === 49) {
        await unlink(temporary).catch(() => {})
        throw error
      }
      await new Promise(r => setTimeout(r, 100))
    }
  }
}

export async function migrateBuildingGeometry(options:Options) {
  if (!options.regionKeys.size || options.regionKeys.size > 256) throw new Error('Explicit bounded region selection (1..256) required')
  if (!Number.isInteger(options.limit) || options.limit < 1 || options.limit > 256) throw new Error('Invalid migration limit')
  if (!Number.isFinite(options.minFreeBytes) || options.minFreeBytes < 0) throw new Error('Invalid storage reserve')
  const catalogPath = join(options.catalogRoot, 'catalog.json')
  let original = await readFile(catalogPath, 'utf8')
  const catalog = JSON.parse(original), groups = groupBuildingRegions<any>(catalog.regions)
  for (const key of options.regionKeys) {
    const rows = groups.get(key)
    if (!rows) throw new Error(`Missing selected region ${key}`)
    if (rows.length !== 1) throw new Error(`Duplicate selected region ${key}; resolve publication ownership first`)
  }
  const report = { revision: BUILDING_MESH_REVISION, source: catalog.source, migrated: 0, skipped: 0, activated: false,
    selected: [...options.regionKeys], remaining: options.regionKeys.size, regions: [] as { key:string; previous:string; next:string; buildings:number; identitySHA256:string }[] }
  const reserve = async (bytes = 0) => {
    const disk = await statfs(options.assetRoot)
    if (disk.bavail * disk.bsize < options.minFreeBytes + bytes) throw new Error('Geometry migration storage reserve reached')
  }
  for (const key of options.regionKeys) {
    const row = groups.get(key)![0]!
    if (!/^[\w-]+$/.test(row.id)) throw new Error(`Invalid region asset ID ${key}`)
    if (options.resume && row.meshRevision === BUILDING_MESH_REVISION) {
      if (!await regionAssetsComplete(options.catalogRoot, row)) throw new Error(`Incomplete v3 assets ${key}`)
      let receipt: any
      try { receipt = JSON.parse(await readFile(join(options.catalogRoot, row.id, 'geometry-migration.json'), 'utf8')) }
      catch (error:any) { if (error.code !== 'ENOENT' || row.geometryMigration) throw error }
      if (receipt) {
        if (receipt.afterIdentitySHA256 !== identity(JSON.parse(await readFile(join(options.catalogRoot, row.id, 'footprints.json'), 'utf8')))) throw new Error(`Incomplete v3 identity ${key}`)
        for (const [name, expected] of Object.entries(receipt.files) as [string, { sha256:string; bytes:number }][]) {
          if (!/^[\w.-]+$/.test(name)) throw new Error('Invalid receipt filename')
          const bytes = await readFile(join(options.catalogRoot, row.id, name))
          if (bytes.length !== expected.bytes || sha(bytes) !== expected.sha256) throw new Error(`Incomplete v3 checksum ${key}/${name}`)
        }
      }
      report.skipped++; report.remaining--; continue
    }
    if (report.migrated >= options.limit) break
    await reserve()
    const oldFolder = join(options.catalogRoot, row.id)
    const oldFootprints = await readFile(join(oldFolder, 'footprints.json'), 'utf8')
    const previous: Footprint[] = JSON.parse(oldFootprints)
    const next = reconcilePublishedGeometry(previous, await options.decodeRegion(row.x, row.y))
    if (!next.length) throw new Error(`Empty published geometry ${key}`)
    const beforeIdentitySHA256 = identity(previous), afterIdentitySHA256 = identity(next)
    if (beforeIdentitySHA256 !== afterIdentitySHA256) throw new Error(`Published identity changed ${key}`)
    if (row.counts && Object.values(row.counts as Record<string,number>).reduce((a,b)=>a+b,0) !== next.length) throw new Error(`Published count mismatch ${key}`)
    let ground: Buffer | undefined
    try { ground = await readFile(join(oldFolder, 'ground-source.json')) }
    catch (error:any) { if (error.code !== 'ENOENT' || row.groundSource || row.groundPolicy === 'local-dem' || row.groundPolicy === 'layered-ground-v1') throw error }
    if (ground && row.groundRevision && JSON.parse(ground.toString()).fileSignature !== row.groundRevision) throw new Error(`Ground provenance mismatch ${key}`)
    const leaves = new Map<string,Footprint[]>()
    for (const f of next) {
      const parts = f.key.split('/'), z = Number(parts[0]), x = Number(parts[1]), y = Number(parts[2])
      if (z !== 16 || !Number.isInteger(x) || !Number.isInteger(y) || Math.floor(x / 4) !== row.x || Math.floor(y / 4) !== row.y) throw new Error(`Invalid component owner ${f.key}`)
      const leaf = parts.slice(0,3).join('/'), list = leaves.get(leaf) ?? []
      list.push(f); leaves.set(leaf,list)
    }
    const digest = sha(JSON.stringify([BUILDING_MESH_REVISION, 'preserve-published-ground', row.id, sha(oldFootprints), sha(ground ?? ''), next])).slice(0,12)
    const {id,folder} = await createUnpublishedRegionFolder(options.assetRoot, `14-${row.x}-${row.y}-${digest}`)
    const files:Record<string,{sha256:string;bytes:number}> = {}
    const save = async (name:string, content:string|Uint8Array) => {
      const bytes = typeof content === 'string' ? Buffer.from(content) : content
      await reserve(bytes.length); await writeFile(join(folder,name),bytes,{flag:'wx'})
      const check = await readFile(join(folder,name))
      if (check.length !== bytes.length || sha(check) !== sha(bytes)) throw new Error(`Asset verification failed ${name}`)
      files[name]={sha256:sha(check),bytes:check.length}
    }
    const bbox = (features:Footprint[]) => features.reduce((a,f)=>{const b=meshFootprintBounds(f);return [Math.min(a[0]!,b[0]),Math.min(a[1]!,b[1]),Math.max(a[2]!,b[2]),Math.max(a[3]!,b[3])]},[Infinity,Infinity,-Infinity,-Infinity])
    const b = bbox(next), origin = frame((b[0]!+b[2]!)/2,(b[1]!+b[3]!)/2)
    const node = async (z:number,x:number,y:number,features:Footprint[],children:any[]) => {
      const bounds=bbox(features), coarse=z<16, uri=`${z}-${x}-${y}.b3dm`
      let min=-12,max=-Infinity,error=0
      for(const f of features){min=Math.min(min,f.z!-12);max=Math.max(max,f.z!+f.h+1)
        if(coarse){const r=meshFootprintBounds(f);error=Math.max(error,Math.hypot((r[2]-r[0])*111320*Math.cos(f.ring[0]![1]!*Math.PI/180),(r[3]-r[1])*111320))}}
      await save(uri,bakeMesh(features,origin,coarse))
      return {boundingVolume:{region:[...bounds.map(v=>v*Math.PI/180),min,max]},geometricError:error*(z===14?2:1),refine:'REPLACE',content:{uri},...(children.length?{children}:{})}
    }
    const mids=[]
    for(let dx=0;dx<2;dx++)for(let dy=0;dy<2;dy++){
      const x=row.x*2+dx,y=row.y*2+dy,children=[],features:Footprint[]=[]
      for(let a=0;a<2;a++)for(let c=0;c<2;c++){const tx=x*2+a,ty=y*2+c,leaf=leaves.get(`16/${tx}/${ty}`);if(!leaf?.length)continue
        features.push(...leaf);children.push(await node(16,tx,ty,leaf,[]))}
      if(features.length)mids.push(await node(15,x,y,features,children))
    }
    const root=await node(14,row.x,row.y,next,mids)
    await save('tileset.json',JSON.stringify({asset:{version:'1.0',tilesetVersion:digest},geometricError:root.geometricError*2,root:{...root,transform:origin.transform}}))
    await save('footprints.json',JSON.stringify(next))
    if(ground)await save('ground-source.json',ground)
    await save('geometry-migration.json',JSON.stringify({revision:BUILDING_MESH_REVISION,previousRegion:row.id,source:catalog.source,beforeIdentitySHA256,afterIdentitySHA256,files:{...files}}))
    if(resolve(options.assetRoot)!==resolve(options.catalogRoot)){
      try{await symlink(folder,join(options.catalogRoot,id),'junction')}catch(error:any){if(error.code!=='EEXIST'||await realpath(join(options.catalogRoot,id))!==await realpath(folder))throw error}
    }
    const replacement={...row,id,meshRevision:BUILDING_MESH_REVISION,geometryMigration:'preserve-published-ground-v1',bounds:[Math.min(row.bounds[0],b[0]!),Math.min(row.bounds[1],b[1]!),Math.max(row.bounds[2],b[2]!),Math.max(row.bounds[3],b[3]!)],
      url:`/world-buildings/${id}/tileset.json`,footprints:`/world-buildings/${id}/footprints.json`,...(ground?{groundSource:`/world-buildings/${id}/ground-source.json`}:{})}
    if(!await regionAssetsComplete(options.catalogRoot,replacement))throw new Error(`Candidate incomplete ${key}`)
    if(await readFile(catalogPath,'utf8')!==original)throw new Error('Catalog changed outside single-writer lock')
    catalog.regions=catalog.regions.map((r:any)=>r.z===row.z&&r.x===row.x&&r.y===row.y?replacement:r)
    await atomicJson(catalogPath,catalog);original=JSON.stringify(catalog)
    report.migrated++;report.remaining--
    report.regions.push({key,previous:row.id,next:id,buildings:next.length,identitySHA256:afterIdentitySHA256})
    await atomicJson(join(options.catalogRoot,'last-geometry-migration.json'),report)
  }
  await atomicJson(join(options.catalogRoot,'last-geometry-migration.json'),report)
  return report
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  if (process.env.WORLD_GEOMETRY_LOCK_HELD !== '1') throw new Error('Use infra/data/migrate_building_geometry.py to acquire the national-buildings lock')
  const required=(key:string)=>{const value=process.env[key];if(!value)throw new Error(`Missing ${key}`);return value}
  const root=required('WORLD_BUILDINGS_OUTPUT'),archivePath=required('WORLD_BUILDINGS_ARCHIVE')
  const catalog=JSON.parse(await readFile(join(root,'catalog.json'),'utf8'))
  const manifest=JSON.parse(await readFile(join(dirname(archivePath),'manifest.json'),'utf8'))
  if(!manifest.version||typeof catalog.source!=='string'||!catalog.source.includes(`/${manifest.version}/`))throw new Error('Archive version does not match catalog source')
  const selection=await readRegionFilter(required('WORLD_BUILDINGS_REGIONS_FILE'))
  const local=await openLocalArchive(archivePath),archive=new PMTiles(local)
  try{
    const report=await migrateBuildingGeometry({catalogRoot:root,assetRoot:required('WORLD_BUILDINGS_ASSET_OUTPUT'),regionKeys:selection!,
      limit:Number(process.env.WORLD_GEOMETRY_LIMIT??16),resume:process.env.WORLD_GEOMETRY_RESUME==='1',minFreeBytes:Number(process.env.WORLD_GEOMETRY_RESERVE_BYTES??20_000_000_000),
      decodeRegion:async(x,y)=>{const out:Footprint[]=[];for(let a=0;a<4;a++)for(let b=0;b<4;b++){
        const tx=x*4+a,ty=y*4+b,data=await archive.getZxy(16,tx,ty)
        if(data)out.push(...await decodeBuildings(new Uint8Array(data.data),{z:16,x:tx,y:ty,key:`16/${tx}/${ty}`},Pbf,VectorTile))}return out}})
    console.log(JSON.stringify(report))
  }finally{await local.close()}
}
