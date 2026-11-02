import { createHash } from 'node:crypto'
import { createReadStream, readFileSync } from 'node:fs'
import { appendFile, copyFile, link, lstat, mkdir, readdir, readFile, rm, stat, statfs, writeFile } from 'node:fs/promises'
import { basename, join, resolve } from 'node:path'
import { gunzipSync } from 'node:zlib'
import { createCandidateStage, encodeCandidatePayload, NGII_ASSET_PACKING, parseReserveGiB, renameCandidateAtomically, verifyExistingCandidate } from './bake-ngii-region'
import { LOD_CODE_SHA256, readRegionalHlodLeaf } from './ngii-global-hlod'
import { bakeMesh, frame, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { generalizeBuildings, localProjection, REGION_LOD_EPS_METRES, REGION_LOD_REVISION, REGION_ROOT_EPS_METRES } from '../features/world/lib/generalize-buildings'
import { footprintBounds, type Footprint } from '../features/world/lib/building-geometry'

/**
 * Re-LOD an existing regional bake into a NEW root (never edits the source root), two generalized levels:
 *   R0 (z14 root)  = generalization at REGION_ROOT_EPS_METRES of the whole region, measured geometricError;
 *   R1 (z15 nodes) = generalization at REGION_LOD_EPS_METRES of each quadrant's buildings, measured per quadrant;
 *   z16 leaves under their quadrant. A quadrant's members are exactly the buildings of its baked leaves (read from
 *   the leaf batch tables), so REPLACE refinement never shows a building twice or drops one. An R1 node is used only
 *   when it is smaller than its leaves and finer than the root; otherwise the leaves hang directly under the root.
 * Leaves, footprints.json.gz and ground-source.json.gz are carried byte-identical.
 * Entry error (what the national HLOD reads): the root's own measured error, written as top = 2 x root like the bake.
 * The HLOD adds its own simplification error above it, so no extra margin is carried; R0 >= R1 >= 0 by construction.
 */
const sha = (bytes: Uint8Array | string) => createHash('sha256').update(bytes).digest('hex')
const fileSHA = async (path: string) => { const h = createHash('sha256'); for await (const b of createReadStream(path)) h.update(b); return h.digest('hex') }
const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))
const REGION_NAME = /^14-(\d+)-(\d+)-[a-f0-9]{16}$/
/** Receipt fields that identify the regional candidate; carried unchanged so downstream gates still match. */
const IDENTITY_KEYS = ['schema', 'completeRegion', 'inputSHA256', 'sourcePlanSHA256', 'sourcePlanFileSHA256', 'terrainSHA256', 'terrainContract',
  'meshRevision', 'assetPacking', 'inventorySHA256', 'owner', 'buildings', 'components'] as const
type FileRow = { path: string; bytes: number; sha256: string; contentEncoding?: 'gzip'; decodedBytes?: number; decodedSHA256?: string }
type TileNode = { boundingVolume: { region: number[] }; geometricError: number; refine: string; content?: { uri: string }; children?: TileNode[]; transform?: number[] }

export function parseShard(value?: string): { index: number; count: number } {
  if (value === undefined) return { index: 0, count: 1 }
  const m = /^(\d+)\/(\d+)$/.exec(value)
  if (!m || Number(m[2]) < 1 || Number(m[1]) >= Number(m[2])) throw Error('Shard must be k/n with 0<=k<n')
  return { index: Number(m[1]), count: Number(m[2]) }
}

export async function listRegionFolders(root: string) {
  const byOwner = new Map<string, string>()
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const m = REGION_NAME.exec(entry.name)
    if (!entry.isDirectory() || !m) continue
    const owner = `14/${m[1]}/${m[2]}`
    if (byOwner.has(owner)) throw Error(`Duplicate regional candidate for ${owner}`)
    byOwner.set(owner, join(root, entry.name))
  }
  return [...byOwner].map(([owner, folder]) => ({ owner, folder })).sort((a, b) => a.owner < b.owner ? -1 : a.owner > b.owner ? 1 : 0)
}

export function relodIdentity(receipt: Record<string, unknown>, receiptSHA256: string) {
  const identity: Record<string, unknown> = {}
  for (const key of IDENTITY_KEYS) identity[key] = receipt[key]
  return { ...identity, lodRevision: REGION_LOD_REVISION, lodSourceReceiptSHA256: receiptSHA256 }
}
/** Source hashes of everything that decides re-LOD output bytes: this file, the generalizer and the mesh baker. */
export const RELOD_CODE_SHA256 = { 'relod-ngii-regions.ts': sha(readFileSync(import.meta.path)), ...LOD_CODE_SHA256 }
/** New immutable name: same owner, digest over the source receipt, the LOD revision and the code that writes the bytes
 * (no stale immutable cache hits, even when a code change forgot the revision bump). */
export function relodName(owner: string, receiptSHA256: string) {
  const digest = sha(JSON.stringify({ sourceReceiptSHA256: receiptSHA256, lodRevision: REGION_LOD_REVISION, eps: [REGION_ROOT_EPS_METRES, REGION_LOD_EPS_METRES], code: RELOD_CODE_SHA256 }))
  return { digest, name: `${owner.replaceAll('/', '-')}-${digest.slice(0, 16)}` }
}

/** z16 leaves of a bake tree (root -> z15 -> z16), in tree order. A leaf payload belongs to exactly one quadrant,
 * otherwise R1 membership would show its buildings twice. */
export function bakedLeaves(tileset: { root: TileNode }): TileNode[] {
  const leaves = (tileset.root.children ?? []).flatMap(c15 => c15.children ?? [])
  if (!leaves.length) throw Error('Regional tileset has no z16 leaves')
  const uris = leaves.map(l => l.content?.uri)
  if (new Set(uris).size !== uris.length) throw Error('Regional leaf payload assigned to more than one node')
  for (const leaf of leaves) if (leaf.children?.length || leaf.geometricError !== 0 || !/^16-\d+-\d+\.b3dm\.gz$/.test(leaf.content?.uri ?? '')) throw Error('Unexpected regional leaf node')
  return leaves
}

export function relodTileset(old: { root: TileNode & { transform: number[] } }, rootUri: string, rootError: number, region: number[], children: TileNode[], version: string) {
  if (!(Number.isFinite(rootError) && rootError >= 0 && rootError <= old.root.geometricError)) throw Error('Generalized root error out of range')
  if (children.some(c => !(c.geometricError >= 0 && c.geometricError <= rootError))) throw Error('Child error above root error')
  return { asset: { version: '1.0', tilesetVersion: version }, geometricError: 2 * rootError,
    root: { boundingVolume: { region }, geometricError: rootError, refine: 'REPLACE', content: { uri: rootUri }, children, transform: old.root.transform } }
}
const growRegion = (region: number[], features: Footprint[]) => {
  for (const f of features) {
    const b = meshFootprintBounds(f)
    region[0] = Math.min(region[0]!, b[0] * Math.PI / 180); region[1] = Math.min(region[1]!, b[1] * Math.PI / 180)
    region[2] = Math.max(region[2]!, b[2] * Math.PI / 180); region[3] = Math.max(region[3]!, b[3] * Math.PI / 180)
    region[4] = Math.min(region[4]!, Math.min(0, f.z!) - 12); region[5] = Math.max(region[5]!, f.z! + f.h + 1)
  }
  return region
}

const batchKeys = (b3dm: Uint8Array) => {
  const h = new DataView(b3dm.buffer, b3dm.byteOffset, b3dm.byteLength), ft = h.getUint32(12, true), bt = h.getUint32(20, true)
  return JSON.parse(new TextDecoder().decode(b3dm.subarray(28 + ft, 28 + ft + bt))).key as string[]
}

/**
 * Root batch table columns for site hiding: each feature's footprint bbox in degrees (a block's lon/lat is just
 * one outline vertex), and lodBlock (1 = merged block, 0 = landmark) marking the content as generalized, not leaf.
 */
export function withLodColumns(b3dm: Uint8Array, features: Footprint[]): Uint8Array {
  const h = new DataView(b3dm.buffer, b3dm.byteOffset, b3dm.byteLength)
  if (h.getUint32(0, true) !== 0x6d643362 || h.getUint32(16, true) || h.getUint32(24, true)) throw Error('Unexpected B3DM layout')
  const ft = h.getUint32(12, true), oldEnd = 28 + ft + h.getUint32(20, true)
  if (JSON.parse(new TextDecoder().decode(b3dm.subarray(28, 28 + ft))).BATCH_LENGTH !== features.length) throw Error('Root batch count mismatch')
  const table = JSON.parse(new TextDecoder().decode(b3dm.subarray(28 + ft, oldEnd))), boxes = features.map(footprintBounds)
  const raw = encode({ ...table, west: boxes.map(b => b[0]), south: boxes.map(b => b[1]), east: boxes.map(b => b[2]), north: boxes.map(b => b[3]),
    lodBlock: features.map(f => f.key.startsWith('blk:') ? 1 : 0) })
  const bt = new Uint8Array(Math.ceil(raw.length / 8) * 8).fill(32); bt.set(raw)
  const out = new Uint8Array(28 + ft + bt.length + b3dm.length - oldEnd)
  out.set(b3dm.subarray(0, 28 + ft)); out.set(bt, 28 + ft); out.set(b3dm.subarray(oldEnd), 28 + ft + bt.length)
  const header = new DataView(out.buffer); header.setUint32(8, out.length, true); header.setUint32(20, bt.length, true)
  return out
}

/** A generalized root larger than the bake root is still accepted up to this multiple of its bytes. */
export const RELOD_ROOT_BYTES_SLACK = 1.5
/** Generalized R0 replaces the bake root when its measured error is lower and its bytes stay within the slack. */
export const useGeneralizedRoot = (error: number, bytes: number, bakeError: number, bakeBytes: number) =>
  error < bakeError && bytes <= RELOD_ROOT_BYTES_SLACK * bakeBytes

export type RelodOptions = { output: string; checkSpace: () => Promise<void>; linkUnchanged?: boolean; rebuildLeaves?: boolean }
export async function relodRegion(folder: string, owner: string, options: RelodOptions) {
  const t0 = performance.now()
  const receiptRaw = await readFile(join(folder, 'candidate-receipt.json')), receipt = JSON.parse(receiptRaw.toString('utf8')), receiptSHA = sha(receiptRaw)
  if (receipt.schema !== 'ngii-region-candidate-v1' || receipt.owner !== owner || receipt.meshRevision !== BUILDING_MESH_REVISION
    || receipt.assetPacking !== NGII_ASSET_PACKING || receipt.lodRevision !== undefined || !Array.isArray(receipt.files)) throw Error(`Unsupported source candidate ${owner}`)
  const identity = relodIdentity(receipt, receiptSHA), { digest, name } = relodName(owner, receiptSHA), final = join(options.output, name)
  if (await verifyExistingCandidate(final, identity)) return { folder: final, owner, resumed: true }
  const rows = new Map<string, FileRow>((receipt.files as FileRow[]).map(f => [f.path, f]))
  const read = (file: string) => readFile(join(folder, file))
  // Same receipt gates as the national HLOD reader: footprints + tileset hashes, counts, bounds, absolute frame.
  const source = await readRegionalHlodLeaf(receipt, read)
  const tilesetRaw = await read('tileset.json')
  if (sha(tilesetRaw) !== rows.get('tileset.json')?.sha256) throw Error('Regional tileset changed')
  const old = JSON.parse(tilesetRaw.toString('utf8')), leaves = bakedLeaves(old), features = source.features as Footprint[]
  const [cx, cy] = [(receipt.bounds[0] + receipt.bounds[2]) / 2, (receipt.bounds[1] + receipt.bounds[3]) / 2], origin = frame(cx, cy)
  const tLoad = performance.now()

  // Quadrant membership = the buildings of the quadrant's baked leaves (the bake groups leaves by building anchor).
  const byKey = new Map(features.map(f => [f.key, f])), seen = new Set<string>(), leafKeys = new Map<string, string[]>()
  for (const leaf of leaves) {
    const uri = leaf.content!.uri
    const raw = await read(uri)
    if (sha(raw) !== rows.get(uri)?.sha256) throw Error(`Leaf ${uri} payload mismatch`)
    const decoded = gunzipSync(raw)
    if (sha(decoded) !== rows.get(uri)!.decodedSHA256) throw Error(`Leaf ${uri} decoded payload mismatch`)
    const keys = batchKeys(decoded)
    for (const k of keys) { if (!byKey.has(k) || seen.has(k)) throw Error(`Leaf ${uri} key not in footprints exactly once`); seen.add(k) }
    leafKeys.set(uri, keys)
  }
  if (seen.size !== features.length) throw Error('Leaves do not cover every component')
  const projection = localProjection(cx, cy)
  const level = (items: Footprint[], eps: number) => {
    const gen = generalizeBuildings(items, projection, eps), covered = gen.members.flat()
    if (covered.length !== items.length || new Set(covered).size !== items.length) throw Error('Generalized level lost or duplicated a component')
    return { gen, payload: encodeCandidatePayload(withLodColumns(bakeMesh(gen.features, origin, false), gen.features)) }
  }
  const r0 = level(features, REGION_ROOT_EPS_METRES)
  const [rx, ry] = owner.split('/').slice(1).map(Number), rootUri = `14-${rx}-${ry}.b3dm.gz`
  // Tiny regions: when generalizing gains nothing (error not below the bake root's) or costs more than the byte slack,
  // the bake root is carried byte-identical with its own error.
  const oldRootUri = old.root.content.uri as string, oldRootRow = rows.get(oldRootUri)
  if (!oldRootRow) throw Error('Source receipt lacks the regional root')
  // A deduped leaf may already be named like the region root: never write R0 over it.
  const generalized = !leaves.some(l => l.content!.uri === rootUri)
    && useGeneralizedRoot(r0.gen.stats.geometricError, r0.payload.bytes.length, old.root.geometricError, oldRootRow.bytes)
  const rootError = generalized ? r0.gen.stats.geometricError : old.root.geometricError
  const quadrants: { uri: string; node: TileNode; r1?: ReturnType<typeof level>; stats: ReturnType<typeof level>['gen']['stats']; gzBytes: number; leafGzBytes: number }[] = []
  for (const c15 of old.root.children as TileNode[]) {
    const qLeaves = c15.children ?? [], keys = new Set(qLeaves.flatMap(l => leafKeys.get(l.content!.uri)!))
    const m = /^15-(\d+)-(\d+)\.b3dm\.gz$/.exec(c15.content?.uri ?? '')
    if (!m || !qLeaves.length) throw Error('Unexpected regional z15 node')
    const uri = `15-${m[1]}-${m[2]}.b3dm.gz`, leafGzBytes = qLeaves.reduce((s, l) => s + rows.get(l.content!.uri)!.bytes, 0)
    const r1 = level(features.filter(f => keys.has(f.key)), REGION_LOD_EPS_METRES)
    // The bake dedups identical payloads, so the z15 file can also be a leaf or the carried bake root: writing R1 under
    // that name would replace it. Such quadrants keep their leaves directly.
    const shared = qLeaves.some(l => l.content!.uri === uri) || (!generalized && oldRootUri === uri)
    const use = !shared && r1.payload.bytes.length < leafGzBytes && r1.gen.stats.geometricError < rootError
    quadrants.push({ uri, ...(use ? { r1 } : {}), stats: r1.gen.stats, gzBytes: r1.payload.bytes.length, leafGzBytes,
      node: { boundingVolume: { region: growRegion([...c15.boundingVolume.region], r1.gen.features) }, geometricError: r1.gen.stats.geometricError,
        refine: 'REPLACE', content: { uri }, children: qLeaves } })
  }
  const region = growRegion([...old.root.boundingVolume.region], generalized ? r0.gen.features : [])
  for (const q of quadrants) if (q.r1) {
    const b = q.node.boundingVolume.region
    for (const k of [0, 1, 4]) region[k] = Math.min(region[k]!, b[k]!)
    for (const k of [2, 3, 5]) region[k] = Math.max(region[k]!, b[k]!)
  }
  const tileset = relodTileset(old, generalized ? rootUri : oldRootUri, rootError, region, quadrants.flatMap(q => q.r1 ? [q.node] : q.node.children!), digest)
  const tGen = performance.now()

  const leafUris = [...new Set(leaves.map(l => l.content!.uri))]
  if (options.rebuildLeaves) { // Prove the carried leaves are exactly what bake-ngii-region would bake from these footprints.
    for (const uri of leafUris) {
      if (sha(bakeMesh(leafKeys.get(uri)!.map(k => byKey.get(k)!), origin, false)) !== rows.get(uri)?.decodedSHA256) throw Error(`Leaf ${uri} does not rebuild byte-identically`)
    }
  }

  await options.checkSpace()
  const stage = await createCandidateStage(options.output, name, identity, options.checkSpace)
  const files: FileRow[] = []
  const carry = async (file: string) => {
    const row = rows.get(file)
    if (!row) throw Error(`Source receipt lacks ${file}`)
    if (files.some(f => f.path === file)) return // the bake may share one payload between nodes
    const path = join(stage.folder, file), part = path + '.part', src = join(folder, file)
    const matches = async (p: string) => { const s = await lstat(p); return s.isFile() && !s.isSymbolicLink() && s.size === row.bytes && await fileSHA(p) === row.sha256 }
    try { if (!await matches(path)) throw Error('Completed staging payload mismatch') }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
      await options.checkSpace()
      await rm(part, { force: true })
      if (options.linkUnchanged) await link(src, part); else await copyFile(src, part)
      if (!await matches(part)) throw Error(`Carried payload ${file} mismatch`)
      await renameCandidateAtomically(part, path)
    }
    files.push(row)
  }
  const save = async (file: string, bytes: Uint8Array, encoding?: ReturnType<typeof encodeCandidatePayload>['metadata']) => {
    await stage.save(file, bytes); files.push({ path: file, bytes: bytes.length, sha256: sha(bytes), ...encoding })
  }
  if (generalized) await save(rootUri, r0.payload.bytes, r0.payload.metadata); else await carry(oldRootUri)
  for (const q of quadrants) if (q.r1) await save(q.uri, q.r1.payload.bytes, q.r1.payload.metadata)
  for (const uri of leafUris) await carry(uri)
  await carry('footprints.json.gz')
  await carry('ground-source.json.gz')
  await save('tileset.json', encode(tileset))
  const { files: _files, note: _note, ...kept } = receipt
  const lod = { ...r0.gen.stats, rootSource: generalized ? 'generalized' : 'carried-bake-root', rootGeometricError: rootError, entryGeometricError: rootError,
    sourceEntryGeometricError: old.root.geometricError, rootGzBytes: generalized ? r0.payload.bytes.length : oldRootRow.bytes, sourceRootGzBytes: oldRootRow.bytes,
    quadrants: quadrants.map(q => ({ uri: q.uri, used: !!q.r1, gzBytes: q.gzBytes, leafGzBytes: q.leafGzBytes, ...q.stats })) }
  const next = { ...kept, ...identity, note: `Re-LOD of ${basename(folder)}: ${generalized ? 'generalized' : 'carried bake'} root, ${quadrants.filter(q => q.r1).length} generalized z15 quadrant(s); leaves, footprints and ground evidence carried byte-identical.`,
    lodSourceFolder: basename(folder), lodCodeSHA256: RELOD_CODE_SHA256, lod, files }
  // The output must stay readable by the national HLOD builder before it becomes visible.
  const check = await readRegionalHlodLeaf(next, file => readFile(join(stage.folder, file)))
  if (check.error !== rootError || check.features.length !== source.features.length) throw Error('Re-LOD entry error is not the root error')
  await stage.finish(next)
  const tDone = performance.now()
  return { folder: final, owner, resumed: false, lod, files: files.length, bytes: files.reduce((s, f) => s + f.bytes, 0) + encode(next).length,
    sourceBytes: (receipt.files as FileRow[]).reduce((s, f) => s + f.bytes, 0) + receiptRaw.length, ms: { load: tLoad - t0, generalize: tGen - tLoad, write: tDone - tGen, total: tDone - t0 } }
}

/**
 * Pins of the source root are re-bound to the output root so downstream gates resolve against it. Concurrent shards
 * publish atomically (complete .part file, then link: no-replace), so a reader sees a whole pin or none; a parse
 * failure (a pin written non-atomically by an older writer) is retried briefly.
 */
export async function bindPin(path: string, value: unknown, pause = (ms: number) => new Promise(r => setTimeout(r, ms))) {
  const encoded = JSON.stringify(value)
  for (let attempt = 0; ; attempt++) {
    try {
      if (JSON.stringify(JSON.parse(await readFile(path, 'utf8'))) !== encoded) throw Error('Candidate output source/terrain identity mismatch')
      return
    } catch (error) {
      if (attempt >= 20) throw error
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        const part = `${path}.${process.pid}-${Math.random().toString(36).slice(2)}.part`
        await writeFile(part, encoded, { flag: 'wx' })
        try { await link(part, path) } catch (e) { if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e } finally { await rm(part, { force: true }) }
      } else if (error instanceof SyntaxError) await pause(50)
      else throw error
    }
  }
}

// Candidate-only: never writes the served catalog, the HLOD or the release pointer.
export async function main(args = process.argv.slice(2)) {
  const option = (name: string) => { const i = args.indexOf(name); if (i < 0 || !args[i + 1] || args[i + 1]!.startsWith('--')) throw Error(`Missing ${name}`); return args[i + 1]! }
  const input = resolve(option('--input')), output = resolve(option('--output'))
  if (input === output) throw Error('Output must be a new root')
  const shard = parseShard(args.includes('--shard') ? option('--shard') : undefined)
  const wanted = new Set(args.flatMap((a, i) => a === '--region' ? [args[i + 1]!] : []))
  const limit = args.includes('--limit') ? Number(option('--limit')) : undefined
  if (limit !== undefined && (!Number.isInteger(limit) || limit < 1)) throw Error('Invalid --limit')
  const reserveGiB = parseReserveGiB(args.includes('--reserve-gib') ? option('--reserve-gib') : undefined), reserve = reserveGiB * 1024 ** 3
  const checkSpace = async () => { const s = await statfs(output); if (s.bavail * s.bsize < reserve) throw Error(`needs_storage: re-LOD output crossed ${reserveGiB}GiB free-space reserve`) }
  const sourcePinRaw = await readFile(join(input, 'candidate-inputs.json')), sourcePin = JSON.parse(sourcePinRaw.toString('utf8'))
  if (sourcePin.mesh !== BUILDING_MESH_REVISION || sourcePin.assetPacking !== NGII_ASSET_PACKING) throw Error('Source root mesh/packing identity mismatch')
  await mkdir(output, { recursive: true })
  await checkSpace()
  // The pin carries the code hash: rerunning failed regions after a code edit must fail instead of mixing outputs.
  await bindPin(join(output, 'candidate-inputs.json'), { ...sourcePin, lodRevision: REGION_LOD_REVISION, lodCodeSHA256: RELOD_CODE_SHA256, lodSourceRoot: input, lodSourceInputsSHA256: sha(sourcePinRaw) })
  try {
    const queueRaw = await readFile(join(input, 'queue-inputs.json')), queue = JSON.parse(queueRaw.toString('utf8'))
    await bindPin(join(output, 'queue-inputs.json'), { ...queue, output, lodSourceOutput: queue.output, lodSourceQueueInputsSHA256: sha(queueRaw) })
  } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
  let regions = (await listRegionFolders(input)).filter(r => !wanted.size || wanted.has(r.owner))
  if (wanted.size && regions.length !== wanted.size) throw Error('Requested region not found in the source root')
  regions = regions.filter((_, i) => i % shard.count === shard.index)
  if (limit !== undefined) regions = regions.slice(0, limit)
  const totals = { regions: 0, resumed: 0, failed: 0, sourceBytes: 0, bytes: 0, ms: 0 }
  // One failing region does not stop the shard: it is recorded here (rewritten each run) and retried by a rerun.
  const failures = join(output, `failures-${shard.index}-of-${shard.count}.jsonl`)
  await writeFile(failures, '')
  for (const { owner, folder } of regions) {
    try { await stat(join(output, 'STOP')); console.log(JSON.stringify({ stopped: true, shard: `${shard.index}/${shard.count}` })); break }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
    const receipt = JSON.parse(await readFile(join(folder, 'candidate-receipt.json'), 'utf8'))
    if (receipt.sourcePlanSHA256 !== sourcePin.sourcePlan || receipt.sourcePlanFileSHA256 !== sourcePin.sourcePlanFileSHA256 || receipt.terrainSHA256 !== sourcePin.expectedTerrain
      || receipt.inventorySHA256 !== sourcePin.inventorySHA256 || receipt.terrainContract !== sourcePin.contract) throw Error(`Region ${owner} does not belong to the pinned source root`)
    let result: Awaited<ReturnType<typeof relodRegion>>
    try { result = await relodRegion(folder, owner, { output, checkSpace, linkUnchanged: args.includes('--link-unchanged'), rebuildLeaves: args.includes('--rebuild-leaves') }) }
    catch (error) {
      if (String((error as Error)?.message).startsWith('needs_storage')) throw error
      totals.failed++
      const row = { owner, folder: basename(folder), error: String((error as Error)?.message ?? error) }
      await appendFile(failures, JSON.stringify(row) + '\n'); console.log(JSON.stringify({ failed: true, ...row }))
      continue
    }
    totals.regions++
    if (result.resumed) totals.resumed++
    else { totals.sourceBytes += result.sourceBytes!; totals.bytes += result.bytes!; totals.ms += result.ms!.total }
    console.log(JSON.stringify(result))
  }
  console.log(JSON.stringify({ done: true, shard: `${shard.index}/${shard.count}`, ...totals, candidateOnly: true }))
  if (totals.failed) throw Error(`Re-LOD failed for ${totals.failed} region(s); see ${failures}`)
}
if (import.meta.main) await main()
