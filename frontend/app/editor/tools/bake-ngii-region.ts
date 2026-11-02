import { gzipSync, gunzipSync } from 'node:zlib'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { createReadStream } from 'node:fs'
import { mkdir, readFile, stat, statfs, writeFile, rename, lstat, readdir } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createInterface } from 'node:readline'
import { resolve, join, basename } from 'node:path'
import { Database } from 'bun:sqlite'
import { canonicalRegions, openCanonicalSnapshot, type CanonicalPlan, type CanonicalRegionInventory } from './ngii-canonical-source'
import { PMTiles } from 'pmtiles'
import { openLocalArchive } from './local-building-archive'
import { decodeHeightTile } from '../features/world/lib/terrain-archive'
import { createTerrainHeightContract, TERRAIN_HEIGHT_CONTRACT } from '../features/world/lib/terrain-height-contract'
import { bakeMesh, frame, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { tileXY, type Footprint } from '../features/world/lib/building-geometry'
import { ngiiMeshInput, type CanonicalBuilding } from './ngii-mesh-input'

export const NGII_ASSET_PACKING = 'gzip6-mesh-and-metadata-v1'

/** Region-local content reuse; callers keep every LOD node and its bounds/error. */
type EncodedMesh = { contentEncoding: 'gzip'; decodedBytes: number; decodedSHA256: string }
export function encodeCandidatePayload(decoded: Uint8Array) {
  const metadata: EncodedMesh = { contentEncoding: 'gzip', decodedBytes: decoded.length,
    decodedSHA256: createHash('sha256').update(decoded).digest('hex') }
  return { bytes: gzipSync(decoded, { level: 6 }), metadata }
}
export function createRegionMeshWriter(save: (name: string, bytes: Uint8Array, encoding: EncodedMesh) => Promise<void>) {
  const saved = new Map<string, { uri: string; bytes: number }>()
  return async (uri: string, bytes: Uint8Array): Promise<string> => {
    const sha = createHash('sha256').update(bytes).digest('hex')
    const prior = saved.get(sha)
    if (prior && prior.bytes === bytes.length) return prior.uri
    const encodedUri = uri + '.gz'
    const encoded = encodeCandidatePayload(bytes)
    await save(encodedUri, encoded.bytes, encoded.metadata)
    saved.set(sha, { uri: encodedUri, bytes: bytes.length })
    return encodedUri
  }
}

export function selectRegions<T extends { region14: string }>(regions: T[], owner?: string, limit?: number): T[] {
  if (limit !== undefined && (!Number.isInteger(limit) || limit < 1)) throw Error('Invalid region limit')
  const selected = regions.filter(r => !owner || r.region14 === owner).sort((a, b) => a.region14.localeCompare(b.region14))
  if (!selected.length) throw Error('No matching canonical region')
  return limit === undefined ? selected : selected.slice(0, limit)
}

/** Free-space reserve on the output volume; default 20 GiB, never below 1 GiB. */
export function parseReserveGiB(value?: string): number {
  if (value === undefined) return 20
  const gib = Number(value)
  if (!Number.isFinite(gib) || gib < 1) throw Error('Invalid --reserve-gib')
  return gib
}

export function shardRegions<T>(selected:T[],index=0,count=1):T[]{
  if(![1,2].includes(count)||!Number.isInteger(index)||index<0||index>=count)throw Error('Invalid shard ownership')
  return selected.filter((_,i)=>i%count===index)
}
export async function bindCandidateInputs(path:string,identity:unknown,requireExisting=false){
  const encoded=JSON.stringify(identity)
  try{if(JSON.stringify(JSON.parse(await readFile(path,'utf8')))!==encoded)throw Error('Candidate output source/terrain identity mismatch')}
  catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error;if(requireExisting)throw Error('Parallel candidate pin must be initialized by coordinator');await writeFile(path,encoded,{flag:'wx'})}
}

const fileSHA = async (path: string) => {
  const hash = createHash('sha256')
  for await (const bytes of createReadStream(path)) hash.update(bytes)
  return hash.digest('hex')
}

export async function verifyExistingCandidate(folder: string, identity: Record<string, unknown>): Promise<boolean> {
  try { await stat(folder) } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false
    throw error
  }
  const receipt = JSON.parse(await readFile(join(folder, 'candidate-receipt.json'), 'utf8'))
  if (Object.entries(identity).some(([key, value]) => receipt[key] !== value)) throw Error('Existing candidate identity mismatch')
  if (!Array.isArray(receipt.files) || !receipt.files.length) throw Error('Missing candidate payload receipt')
  for (const file of receipt.files) {
    if (typeof file.path !== 'string' || basename(file.path) !== file.path || file.path.includes('\\') || file.path === '..') throw Error('Invalid candidate payload path')
    const path = join(folder, file.path)
    if ((await stat(path)).size !== file.bytes || await fileSHA(path) !== file.sha256) throw Error('Existing candidate payload mismatch')
    if (receipt.assetPacking === NGII_ASSET_PACKING && (file.path.endsWith('.b3dm') || ['footprints.json','ground-source.json'].includes(file.path))) throw Error('Unencoded mesh in gzip packing')
    if (file.path.endsWith('.b3dm.gz') || ['footprints.json.gz','ground-source.json.gz'].includes(file.path)) {
      const decoded = gunzipSync(await readFile(path))
      if (file.contentEncoding !== 'gzip' || decoded.length !== file.decodedBytes
        || createHash('sha256').update(decoded).digest('hex') !== file.decodedSHA256) throw Error('Existing candidate decoded mesh mismatch')
    }
  }
  return true
}

export async function renameCandidateAtomically(from: string, to: string,
  move = rename, pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))) {
  for (let attempt = 0; ; attempt++) {
    try { await lstat(to); throw Error('Immutable candidate destination already exists') }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
    try { await move(from, to); return }
    catch (error) {
      if (attempt >= 4 || !['EPERM','EACCES','EBUSY'].includes((error as NodeJS.ErrnoException).code ?? '')) throw error
      await pause(25 * 2 ** attempt)
    }
  }
}

/** The coordinator owns the single-writer lock. Only this pinned region's .part files may be overwritten. */
export async function createCandidateStage(output: string, name: string, identity: Record<string, unknown>, checkSpace: () => Promise<void>) {
  if (basename(name) !== name || name.includes('\\') || !/^14-\d+-\d+-[a-f0-9]{16}$/.test(name)) throw Error('Invalid immutable region name')
  const staging = join(output, '.staging'), folder = join(staging, name), final = join(output, name)
  await mkdir(staging, { recursive: true })
  const pin = join(staging, name + '.inputs.json'), expected = JSON.stringify(identity)
  try {
    const stamp = await lstat(folder)
    if (!stamp.isDirectory() || stamp.isSymbolicLink()) throw Error('Invalid staging directory')
    if ((await readFile(pin, 'utf8')) !== expected) throw Error('Staging source identity mismatch')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    // An existing directory without its pin is not resumable.
    try { await lstat(folder); throw Error('Unbound staging directory') }
    catch (missing) { if ((missing as NodeJS.ErrnoException).code !== 'ENOENT') throw missing }
    try {
      if (await readFile(pin, 'utf8') !== expected) throw Error('Staging source identity mismatch')
    } catch (existing) {
      if ((existing as NodeJS.ErrnoException).code !== 'ENOENT') throw existing
      await checkSpace()
      const partialPin = pin + '.part'
      try { const stamp = await lstat(partialPin); if (!stamp.isFile() || stamp.isSymbolicLink()) throw Error('Invalid staging pin part') }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
      await writeFile(partialPin, expected)
      if (await readFile(partialPin, 'utf8') !== expected) throw Error('Staging source pin readback mismatch')
      await renameCandidateAtomically(partialPin, pin)
    }
    await mkdir(folder)
  }
  const save = async (file: string, bytes: Uint8Array) => {
    if (basename(file) !== file || file.includes('\\') || file.endsWith('.part')) throw Error('Invalid staged file name')
    const path = join(folder, file), hash = createHash('sha256').update(bytes).digest('hex')
    try {
      const stamp = await lstat(path)
      if (!stamp.isFile() || stamp.isSymbolicLink() || stamp.size !== bytes.length || await fileSHA(path) !== hash) throw Error('Completed staging payload mismatch')
      return
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
    await checkSpace()
    const part = path + '.part'
    try { const stamp = await lstat(part); if (!stamp.isFile() || stamp.isSymbolicLink()) throw Error('Invalid staging part') }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
    await writeFile(part, bytes) // Interrupted bytes are never regarded as completed files.
    if ((await stat(part)).size !== bytes.length || await fileSHA(part) !== hash) throw Error('Staging readback mismatch')
    await renameCandidateAtomically(part, path)
  }
  return { folder, final, save,
    async finish(receipt: { files: { path: string }[] } & Record<string, unknown>) {
      await save('candidate-receipt.json', new TextEncoder().encode(JSON.stringify(receipt, null, 2)))
      const allowed = new Set([...receipt.files.map(f => f.path), 'candidate-receipt.json'])
      if ((await readdir(folder)).some(file => !allowed.has(file))) throw Error('Unexpected staging files remain')
      if (!await verifyExistingCandidate(folder, identity)) throw Error('Incomplete staged candidate')
      await checkSpace()
      await renameCandidateAtomically(folder, final)
    },
  }
}

async function* inputRows(input: string): AsyncGenerator<CanonicalBuilding> {
  const lines = createInterface({ input: createReadStream(input), crlfDelay: Infinity })
  for await (const line of lines) if (line.trim()) yield JSON.parse(line) as CanonicalBuilding
}

// Candidate-only: this command never writes the served catalog or release pointer.
export async function main(args = process.argv.slice(2)) {
  const option = (name: string) => {
    const i = args.indexOf(name)
    if (i < 0 || !args[i + 1] || args[i + 1]!.startsWith('--')) throw Error(`Missing ${name}`)
    return args[i + 1]!
  }
  const input = args.includes('--input') ? resolve(option('--input')) : undefined
  const database = args.includes('--database') ? resolve(option('--database')) : undefined
  const snapshot = args.includes('--snapshot') ? resolve(option('--snapshot')) : undefined
  if ([input, database, snapshot].filter(Boolean).length !== 1) throw Error('Specify exactly one of --input, --database or --snapshot')
  const shardCount=args.includes('--shard-count')?Number(option('--shard-count')):1,shardIndex=args.includes('--shard-index')?Number(option('--shard-index')):0
  shardRegions([],shardIndex,shardCount)
  if(shardCount>1&&!snapshot&&!database)throw Error('Sharded bake requires full canonical inventory')
  const output = resolve(option('--output')), terrainPath = resolve(option('--terrain'))
  const expectedTerrain = option('--terrain-sha256'), planPath = resolve(option('--source-plan'))
  const planBytes = await readFile(planPath), plan = JSON.parse(planBytes.toString('utf8')) as CanonicalPlan
  const sourcePlan = plan.planSHA256, sourcePlanFileSHA256 = createHash('sha256').update(planBytes).digest('hex')
  if (plan.schema !== 'ngii-canonical-plan-v1' || !plan.sources?.length
    || ![expectedTerrain, sourcePlan].every(s => /^[a-f0-9]{64}$/.test(s))) throw Error('Invalid pinned source plan or terrain SHA256')
  if (args.includes('--source-plan-sha256') && option('--source-plan-sha256') !== sourcePlanFileSHA256) throw Error('Source plan file SHA256 mismatch')
  const sourceIdentity = (p: CanonicalBuilding['provenance']) => JSON.stringify([p.family, p.productCode, p.productKind,
    p.layer, p.edition, p.sourceManifestSHA256, p.productReceiptSHA256, p.file])
  const allowedSources = new Set(plan.sources.map(source => sourceIdentity(source.manifest)))
  await mkdir(output, { recursive: true })
  const reserveGiB = parseReserveGiB(args.includes('--reserve-gib') ? option('--reserve-gib') : undefined)
  const reserve = reserveGiB * 1024 ** 3 + (shardCount>1?shardCount*256*1024**2:0)
  const checkSpace = async () => {
    const disk = await statfs(output)
    if (disk.bavail * disk.bsize < reserve) throw Error(`Candidate output crossed ${reserveGiB}GiB free-space reserve`)
  }
  await checkSpace()
  if (snapshot) {
    const verifier = fileURLToPath(new URL('../../../../infra/data/ngii_canonical_snapshot.py', import.meta.url))
    const check = spawnSync(process.env.NGII_PYTHON || 'python', ['-X', 'utf8', verifier, 'verify', '--snapshot', snapshot, '--plan', planPath], { encoding: 'utf8', windowsHide: true })
    if (check.error || check.status !== 0) throw Error(`Canonical snapshot receipt gate failed: ${check.error?.message || check.stderr}`)
  }
  const db = snapshot ? openCanonicalSnapshot(snapshot) : database ? new Database(database, { readonly: true, strict: true }) : undefined
  let source: ReturnType<typeof canonicalRegions> | undefined
  let local: Awaited<ReturnType<typeof openLocalArchive>> | undefined
  try {
    const inventoryBytes = db ? await readFile(resolve(option('--regions'))) : undefined
    const inventory = inventoryBytes ? JSON.parse(inventoryBytes.toString('utf8')) as CanonicalRegionInventory : undefined
    if (db && inventory) source = canonicalRegions(db, plan, inventory)
    const selected = shardRegions<{region14:string}>(source ? selectRegions(source.regions, args.includes('--region') ? option('--region') : undefined,
      args.includes('--limit') ? Number(option('--limit')) : undefined) : [{ region14: '' }],shardIndex,shardCount)
    const inventorySHA256 = inventoryBytes ? createHash('sha256').update(inventoryBytes).digest('hex') : null
    const runIdentity = { sourcePlan, sourcePlanFileSHA256, expectedTerrain, inventorySHA256,
      mode: db ? 'completed-canonical-database' : 'sample-ndjson', mesh: BUILDING_MESH_REVISION, assetPacking: NGII_ASSET_PACKING, contract: TERRAIN_HEIGHT_CONTRACT }
    const pinPath = join(output, 'candidate-inputs.json')
    await checkSpace()
    await bindCandidateInputs(pinPath,runIdentity,shardCount>1&&!args.includes('--initialize-only'))
    const terrainStamp = await stat(terrainPath)
    if (await fileSHA(terrainPath) !== expectedTerrain) throw Error('Terrain archive SHA256 mismatch')
    const assertPinned = async () => {
      if (await fileSHA(planPath) !== sourcePlanFileSHA256) throw Error('Source plan changed during bake')
      const stamp = await stat(terrainPath)
      if (stamp.size !== terrainStamp.size || stamp.mtimeMs !== terrainStamp.mtimeMs || stamp.ctimeMs !== terrainStamp.ctimeMs || stamp.ino !== terrainStamp.ino) throw Error('Terrain archive changed during bake')
    }
    await assertPinned()
    local = await openLocalArchive(terrainPath)
    const archive = new PMTiles(local), metadata = await archive.getMetadata() as {
      schema: string; grid: string; size: number; archiveZoomOffset: number; minLevel: number; maxLevel: number; vrt_sha256: string
    }
    if (metadata.schema !== 'ngii-heightmap-v1' || metadata.grid !== 'Cesium.GeographicTilingScheme'
      || metadata.size !== 33 || metadata.archiveZoomOffset !== 1 || !/^[a-f0-9]{64}$/.test(metadata.vrt_sha256)) throw Error('Invalid terrain archive metadata')
    const contract = createTerrainHeightContract(async ({ level, x, y }) => {
      const tile = await archive.getZxy(level + 1, x, y)
      return tile ? decodeHeightTile(tile.data) : null
    }, { archiveSha256: expectedTerrain, minLevel: metadata.minLevel, maxLevel: metadata.maxLevel, keep: 128 })
    if(args.includes('--initialize-only')){console.log(JSON.stringify({initialized:true,candidateOnly:true}));return}
    for (const selectedRegion of selected) {
      try{await stat(join(output,'STOP'));console.log(JSON.stringify({stopped:true,shardIndex,shardCount,candidateOnly:true}));return}catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error}
      await assertPinned()
      const ownerHint = selectedRegion.region14
      const rowSource = () => source ? source.rows(ownerHint) : inputRows(input!)
      let inputSHA: string
      if (source) {
        const hash = createHash('sha256')
        for (const row of source.rows(ownerHint)) hash.update(JSON.stringify(row) + '\n')
        inputSHA = hash.digest('hex')
      } else inputSHA = await fileSHA(input!)
      const digest = createHash('sha256').update(JSON.stringify({ inputSHA, expectedTerrain, sourcePlan, sourcePlanFileSHA256,
        inventorySHA256, completeRegion: Boolean(source), mesh: BUILDING_MESH_REVISION, assetPacking: NGII_ASSET_PACKING, contract: TERRAIN_HEIGHT_CONTRACT })).digest('hex')
      const identity = { schema: 'ngii-region-candidate-v1', completeRegion: Boolean(source),
        inputSHA256: inputSHA, sourcePlanSHA256: sourcePlan, sourcePlanFileSHA256, terrainSHA256: expectedTerrain,
        terrainContract: TERRAIN_HEIGHT_CONTRACT, meshRevision: BUILDING_MESH_REVISION, assetPacking: NGII_ASSET_PACKING, inventorySHA256 }
      if (ownerHint) {
        const existing = join(output, `${ownerHint.replaceAll('/', '-')}-${digest.slice(0, 16)}`)
        const counts = source!.regions.find(r => r.region14 === ownerHint)!
        if (await verifyExistingCandidate(existing, { ...identity, owner: ownerHint, buildings: counts.buildings, components: counts.components })) {
          console.log(JSON.stringify({ folder: existing, owner: ownerHint, resumed: true }))
          continue
        }
      }
      const features: Footprint[] = [], leaves = new Map<string, Footprint[]>(), seen = new Set<string>()
      const provenance: unknown[] = []
      let owner = '', buildings = 0, supported = 0
      for await (const row of rowSource()) {
        if (!allowedSources.has(sourceIdentity(row.provenance))) throw Error('Canonical row is absent from the pinned source plan')
        const [x, y] = tileXY(row.anchorWGS84[0]!, row.anchorWGS84[1]!, 14), region = `14/${x}/${y}`
        if (owner && owner !== region) throw Error('Input spans multiple owner regions')
        owner = region
        if (seen.has(row.canonicalBuildingId)) throw Error(`Duplicate canonical input ${row.canonicalBuildingId}`)
        seen.add(row.canonicalBuildingId)
        const result = await ngiiMeshInput(row, expectedTerrain, (lon, lat) => contract.samplePosition(lon, lat))
        const [fx, fy] = tileXY(row.anchorWGS84[0]!, row.anchorWGS84[1]!, 16), leaf = `16/${fx}/${fy}`
        const group = leaves.get(leaf) ?? []
        group.push(...result.footprints); leaves.set(leaf, group); features.push(...result.footprints)
        provenance.push({ id: result.canonicalBuildingId, sourceUFID: result.sourceUFID, ground: result.ground,
          heightSource: result.heightSource, provenance: result.provenance })
        buildings++; supported += Number(result.supportedGround)
        if (buildings % 1024 === 0) await checkSpace()
      }
      if (!buildings) throw Error('Empty canonical region')
      if (!source && await fileSHA(input!) !== inputSHA) throw Error('Canonical input changed during bake')
      await assertPinned()
      const folder = join(output, `${owner.replaceAll('/', '-')}-${digest.slice(0, 16)}`)
      if (await verifyExistingCandidate(folder, { ...identity, owner })) {
        console.log(JSON.stringify({ folder, owner, resumed: true }))
        continue
      }
      await checkSpace()
      const stage = await createCandidateStage(output, basename(folder), { ...identity, owner }, checkSpace)
      const boxes = features.map(meshFootprintBounds)
      const box = boxes.reduce((a, b) => [Math.min(a[0]!, b[0]), Math.min(a[1]!, b[1]), Math.max(a[2]!, b[2]), Math.max(a[3]!, b[3])], [Infinity, Infinity, -Infinity, -Infinity])
      const origin = frame((box[0]! + box[2]!) / 2, (box[1]! + box[3]!) / 2)
      const files: ({ path: string; bytes: number; sha256: string } & Partial<EncodedMesh>)[] = []
      const save = async (name: string, bytes: Uint8Array, encoding?: EncodedMesh) => {
        await stage.save(name, bytes)
        const sha256 = createHash('sha256').update(bytes).digest('hex')
        files.push({ path: name, bytes: bytes.length, sha256, ...encoding })
      }
      const saveMesh = createRegionMeshWriter(save)
      const saveMetadata = async (name: string, decoded: Uint8Array) => {
        const encoded = encodeCandidatePayload(decoded)
        await save(name + '.gz', encoded.bytes, encoded.metadata)
      }
      const json = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))
      type Node = { boundingVolume: { region: number[] }; geometricError: number; refine: 'REPLACE'; content: { uri: string }; children?: Node[] }
      const node = async (z: number, x: number, y: number, rows: Footprint[], children: Node[]): Promise<Node> => {
        const b = [Infinity, Infinity, -Infinity, -Infinity], heights = [Infinity, -Infinity]
        let error = 0
        for (const f of rows) {
          const r = meshFootprintBounds(f)
          b[0] = Math.min(b[0]!, r[0]); b[1] = Math.min(b[1]!, r[1]); b[2] = Math.max(b[2]!, r[2]); b[3] = Math.max(b[3]!, r[3])
          heights[0] = Math.min(heights[0]!, Math.min(0, f.z!) - 12); heights[1] = Math.max(heights[1]!, f.z! + f.h + 1)
          error = Math.max(error, Math.hypot((r[2] - r[0]) * 111320 * Math.cos(f.ring[0]![1]! * Math.PI / 180), (r[3] - r[1]) * 111320))
        }
        const uri = await saveMesh(`${z}-${x}-${y}.b3dm`, bakeMesh(rows, origin, z < 16))
        return { boundingVolume: { region: [...b.map(v => v * Math.PI / 180), ...heights] }, geometricError: z === 16 ? 0 : error * (z === 14 ? 2 : 1),
          refine: 'REPLACE', content: { uri }, ...(children.length ? { children } : {}) }
      }
      const [, rx, ry] = owner.split('/').map(Number), children: Node[] = []
      for (let dx = 0; dx < 2; dx++) for (let dy = 0; dy < 2; dy++) {
        const x = rx! * 2 + dx, y = ry! * 2 + dy, group: Footprint[] = [], detailed: Node[] = []
        for (let a = 0; a < 2; a++) for (let b = 0; b < 2; b++) {
          const fx = x * 2 + a, fy = y * 2 + b, rows = leaves.get(`16/${fx}/${fy}`)
          if (!rows?.length) continue
          group.push(...rows); detailed.push(await node(16, fx, fy, rows, []))
        }
        if (group.length) children.push(await node(15, x, y, group, detailed))
      }
      const root = await node(14, rx!, ry!, features, children)
      await save('tileset.json', json({ asset: { version: '1.0', tilesetVersion: digest }, geometricError: root.geometricError * 2, root: { ...root, transform: origin.transform } }))
      await saveMetadata('footprints.json', json(features))
      await saveMetadata('ground-source.json', json({ archiveSha256: expectedTerrain, contract: TERRAIN_HEIGHT_CONTRACT, buildings: provenance }))
      const receipt = { ...identity, note: source ? 'Complete canonical source region; ground support is reported separately.' : 'Sample input does not prove complete region coverage.',
        owner, buildings, components: features.length, supportedGroundBuildings: supported, unresolvedGroundBuildings: buildings - supported,
        inputSHA256: inputSHA, sourcePlanSHA256: sourcePlan, sourcePlanFileSHA256, terrainSHA256: expectedTerrain, terrainContract: TERRAIN_HEIGHT_CONTRACT,
        meshRevision: BUILDING_MESH_REVISION, bounds: box, files }
      await assertPinned()
      await checkSpace()
      await stage.finish(receipt)
      console.log(JSON.stringify({ folder, ...receipt, files: files.length }))
    }
  } finally {
    try { await local?.close() } finally { try { source?.close() } finally { db?.close() } }
  }
}

if (import.meta.main) await main()
