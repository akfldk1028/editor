import { createReadStream } from 'node:fs'
import { mkdir, readFile, statfs, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createInterface } from 'node:readline'
import { resolve, join } from 'node:path'
import { PMTiles } from 'pmtiles'
import { openLocalArchive } from './local-building-archive'
import { decodeHeightTile } from '../features/world/lib/terrain-archive'
import { createTerrainHeightContract, TERRAIN_HEIGHT_CONTRACT } from '../features/world/lib/terrain-height-contract'
import { bakeMesh, frame, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { tileXY, type Footprint } from '../features/world/lib/building-geometry'
import { ngiiMeshInput, type CanonicalBuilding } from './ngii-mesh-input'

// Candidate-only: this command never writes the served catalog or release pointer.
const args = process.argv.slice(2)
const option = (name: string) => {
  const i = args.indexOf(name)
  if (i < 0 || !args[i + 1] || args[i + 1]!.startsWith('--')) throw Error(`Missing ${name}`)
  return args[i + 1]!
}
const input = resolve(option('--input')), output = resolve(option('--output')), terrainPath = resolve(option('--terrain'))
const expectedTerrain = option('--terrain-sha256'), planPath = resolve(option('--source-plan'))
const planBytes = await readFile(planPath), plan = JSON.parse(planBytes.toString('utf8')) as {
  schema: string; planSHA256: string; sources: { manifest: CanonicalBuilding['provenance'] }[]
}
const sourcePlan = plan.planSHA256, sourcePlanFileSHA256 = createHash('sha256').update(planBytes).digest('hex')
if (plan.schema !== 'ngii-canonical-plan-v1' || !plan.sources?.length
  || ![expectedTerrain, sourcePlan].every(s => /^[a-f0-9]{64}$/.test(s))) throw Error('Invalid pinned source plan or terrain SHA256')
const sourceIdentity = (p: CanonicalBuilding['provenance']) => JSON.stringify([p.family, p.productCode, p.productKind,
  p.layer, p.edition, p.sourceManifestSHA256, p.productReceiptSHA256, p.file])
const allowedSources = new Set(plan.sources.map(source => sourceIdentity(source.manifest)))
await mkdir(output, { recursive: true })
const reserve = 20_000_000_000
const checkSpace = async () => {
  const disk = await statfs(output)
  if (disk.bavail * disk.bsize < reserve) throw Error('Candidate output crossed 20GB free-space reserve')
}
await checkSpace()
const fileSHA = async (path: string) => {
  const hash = createHash('sha256')
  for await (const bytes of createReadStream(path)) hash.update(bytes)
  return hash.digest('hex')
}
const inputSHA = await fileSHA(input)
if (await fileSHA(terrainPath) !== expectedTerrain) throw Error('Terrain archive SHA256 mismatch')
const local = await openLocalArchive(terrainPath)
try {
  const archive = new PMTiles(local), metadata = await archive.getMetadata() as {
    schema: string; grid: string; size: number; archiveZoomOffset: number; minLevel: number; maxLevel: number; vrt_sha256: string
  }
  if (metadata.schema !== 'ngii-heightmap-v1' || metadata.grid !== 'Cesium.GeographicTilingScheme'
    || metadata.size !== 33 || metadata.archiveZoomOffset !== 1 || !/^[a-f0-9]{64}$/.test(metadata.vrt_sha256)) throw Error('Invalid terrain archive metadata')
  const contract = createTerrainHeightContract(async ({ level, x, y }) => {
    const tile = await archive.getZxy(level + 1, x, y)
    return tile ? decodeHeightTile(tile.data) : null
  }, { archiveSha256: expectedTerrain, minLevel: metadata.minLevel, maxLevel: metadata.maxLevel, keep: 128 })
  const features: Footprint[] = [], leaves = new Map<string, Footprint[]>(), seen = new Set<string>()
  const provenance: unknown[] = []
  let owner = '', buildings = 0, supported = 0
  const lines = createInterface({ input: createReadStream(input), crlfDelay: Infinity })
  for await (const line of lines) {
    if (!line.trim()) continue
    const row = JSON.parse(line) as CanonicalBuilding
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
  if (await fileSHA(input) !== inputSHA || await fileSHA(planPath) !== sourcePlanFileSHA256) throw Error('Canonical input or source plan changed during bake')
  const digest = createHash('sha256').update(JSON.stringify({ inputSHA, expectedTerrain, sourcePlan, sourcePlanFileSHA256,
    mesh: BUILDING_MESH_REVISION, contract: TERRAIN_HEIGHT_CONTRACT })).digest('hex')
  const folder = join(output, `${owner.replaceAll('/', '-')}-${digest.slice(0, 16)}`)
  await mkdir(folder) // Immutable: an existing candidate is never overwritten.
  const boxes = features.map(meshFootprintBounds)
  const box = boxes.reduce((a, b) => [Math.min(a[0]!, b[0]), Math.min(a[1]!, b[1]), Math.max(a[2]!, b[2]), Math.max(a[3]!, b[3])], [Infinity, Infinity, -Infinity, -Infinity])
  const origin = frame((box[0]! + box[2]!) / 2, (box[1]! + box[3]!) / 2)
  const files: { path: string; bytes: number; sha256: string }[] = []
  const save = async (name: string, bytes: Uint8Array) => {
    await checkSpace()
    const path = join(folder, name)
    await writeFile(path, bytes, { flag: 'wx' })
    const sha256 = createHash('sha256').update(bytes).digest('hex')
    if (await fileSHA(path) !== sha256) throw Error(`Candidate readback mismatch: ${name}`)
    files.push({ path: name, bytes: bytes.length, sha256 })
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
    const uri = `${z}-${x}-${y}.b3dm`
    await save(uri, bakeMesh(rows, origin, z < 16))
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
  await save('footprints.json', json(features))
  await save('ground-source.json', json({ archiveSha256: expectedTerrain, contract: TERRAIN_HEIGHT_CONTRACT, buildings: provenance }))
  const receipt = { schema: 'ngii-region-candidate-v1', completeRegion: false, note: 'Input coverage must be proven by the canonical ingest receipt before publication.',
    owner, buildings, components: features.length, supportedGroundBuildings: supported, unresolvedGroundBuildings: buildings - supported,
    inputSHA256: inputSHA, sourcePlanSHA256: sourcePlan, sourcePlanFileSHA256, terrainSHA256: expectedTerrain, terrainContract: TERRAIN_HEIGHT_CONTRACT,
    meshRevision: BUILDING_MESH_REVISION, bounds: box, files }
  await writeFile(join(folder, 'candidate-receipt.json'), JSON.stringify(receipt, null, 2), { flag: 'wx' })
  console.log(JSON.stringify({ folder, ...receipt, files: files.length }))
} finally { await local.close() }
