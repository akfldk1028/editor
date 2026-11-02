import { mkdir, rename, readFile, writeFile, statfs, symlink, realpath } from 'node:fs/promises'
import { resolve, join, dirname } from 'node:path'
import { createHash } from 'node:crypto'
import { PMTiles } from 'pmtiles'
import { openLocalArchive } from './local-building-archive'
import { preservesCoverage, createUnpublishedRegionFolder, readBuildingCatalog, regionAssetsComplete, readRegionFilter, retainPublishedKeys, groupBuildingRegions, mergePublishedFootprints } from './building-publication-safety'
import { verifyDemFiles, type DemFileStamp } from './dem-file-stamps'
import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { decodeBuildings, tileXY, type Footprint } from '../features/world/lib/building-geometry'
import { bakeMesh, frame, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { canResumeGround, enrichGround, selectGroundLeaves, type GroundSample } from './building-ground-publication'
import { canResumeLayeredGround, enrichLayeredGround, layeredGroundRevision } from './building-ground-layers'
import { COMPOSED_GROUND_POLICY, composedGroundRevision, enrichComposedGround, type ArchiveGroundFallback } from './building-composed-ground'

// --bounds west south east north --resume supports bounded, restartable country-wide jobs.
const args = process.argv.slice(2), area = args[0] === '--bounds'
const lon = Number(area ? args[1] : args[0] ?? 127.1084), lat = Number(area ? args[2] : args[1] ?? 37.7301), radius = Number(area ? 0 : args[2] ?? 0)
if (!Number.isFinite(lon) || !Number.isFinite(lat) || !Number.isInteger(radius) || radius < 0 || radius > 8) throw new Error('Invalid region')
const refreshGround = args.includes('--refresh-ground')
const composedPath = process.env.WORLD_COMPOSED_DEM_PATH
if (composedPath && (!process.env.WORLD_BUILDINGS_REGIONS_FILE || !process.env.WORLD_GROUND_FALLBACK_FILE || !process.env.WORLD_BUILDINGS_ASSET_OUTPUT)) throw Error('Composed ground requires an explicit candidate region set, fallback proof and asset output')
if (refreshGround && !composedPath && !process.env.WORLD_DEM_PATH && !process.env.WORLD_PRECISE_DEM_PATH) throw new Error('--refresh-ground requires a DEM')
const sampleRaster = async (path: string, points: number[][]): Promise<GroundSample & { revisionFiles?: DemFileStamp[] }> => {
  const child = spawnSync(process.env.WORLD_PYTHON || 'python', [
    fileURLToPath(new URL('./sample-building-dem.py', import.meta.url)), path],
    { input: JSON.stringify(points), encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, windowsHide: true })
  if (child.status !== 0) throw new Error(`Local DEM sampling failed: ${child.error || child.stderr}`)
  return JSON.parse(child.stdout)
}
const sampleGround = (points: number[][]) => sampleRaster(process.env.WORLD_DEM_PATH!, points)
const samplePrecise = (points: number[][]) => sampleRaster(process.env.WORLD_PRECISE_DEM_PATH!, points)
const groundMetadata = process.env.WORLD_DEM_PATH ? await sampleGround([]) : undefined
const preciseMetadata = process.env.WORLD_PRECISE_DEM_PATH ? await samplePrecise([]) : undefined
const composedMetadata = composedPath ? await sampleRaster(composedPath, []) : undefined
const fallbackBytes = composedPath ? await readFile(process.env.WORLD_GROUND_FALLBACK_FILE!, 'utf8') : undefined
const fallback = fallbackBytes ? JSON.parse(fallbackBytes) as ArchiveGroundFallback : undefined
const groundRevision = composedMetadata ? composedGroundRevision(composedMetadata.source.fileSignature, fallback!) : preciseMetadata ? layeredGroundRevision({ base: groundMetadata?.source.fileSignature,
  precise: preciseMetadata.source.fileSignature }) : groundMetadata?.source.fileSignature
const verifyGround = async () => {
  if (groundMetadata) await verifyDemFiles(groundMetadata.revisionFiles || [])
  if (preciseMetadata) await verifyDemFiles(preciseMetadata.revisionFiles || [])
  if (composedMetadata) {
    await verifyDemFiles(composedMetadata.revisionFiles || [])
    if (await readFile(process.env.WORLD_GROUND_FALLBACK_FILE!, 'utf8') !== fallbackBytes) throw Error('Archive fallback proof changed')
  }
}
const origin = process.env.WORLD_API_ORIGIN || 'http://127.0.0.1:3003'
const manifest = process.env.WORLD_BUILDINGS_SOURCE ? { href: process.env.WORLD_BUILDINGS_SOURCE }
  : await fetch(`${origin}/api/v1/land/context-tiles`).then(r => { if (!r.ok) throw new Error(`Manifest ${r.status}`); return r.json() }) as { href: string }
const localPath = process.env.WORLD_BUILDINGS_ARCHIVE
if (localPath) {
  const localManifest = JSON.parse(await readFile(join(dirname(localPath), 'manifest.json'), 'utf8'))
  if (!localManifest.version || !manifest.href.includes(`/${localManifest.version}/`)) throw new Error('Local archive version does not match catalog source')
}
const localArchive = localPath ? await openLocalArchive(localPath) : undefined
const archive = new PMTiles(localArchive || manifest.href), [cx, cy] = tileXY(lon, lat, 14)
const output = resolve(process.env.WORLD_BUILDINGS_OUTPUT || 'public/world-buildings')
await mkdir(output, { recursive: true })
const assetOutput = resolve(process.env.WORLD_BUILDINGS_ASSET_OUTPUT || output)
await mkdir(assetOutput, { recursive: true })
const old = await readBuildingCatalog(join(output, 'catalog.json'))
if (old.source && old.source !== manifest.href) throw new Error('Use a separate output directory for a new source snapshot')
const regionGroups = groupBuildingRegions<any>(old.regions)
const regionFilter = await readRegionFilter(process.env.WORLD_BUILDINGS_REGIONS_FILE)
const missingRegions: { key: string; buildings: number; missingDatum: number }[] = []
const groundMetrics: { key: string; status: 'sampled' | 'published' | 'preserved-previous' | 'no-ground';
  beforeMissing: number; newlyFilled: number; preciseOverride: number; remaining: number }[] = []
const [west, south, east, north] = area ? args.slice(1, 5).map(Number) : [lon, lat, lon, lat]
if (area && (![west, south, east, north].every(Number.isFinite) || west! >= east! || south! >= north!
  || west! < 124 || east! > 133 || south! < 33 || north! > 39)) throw new Error('Invalid Korea bounds')
const [minX, minY] = area ? tileXY(west!, north!, 14) : [cx - radius, cy - radius]
const [maxX, maxY] = area ? tileXY(east!, south!, 14) : [cx + radius, cy + radius]
const publish = async () => {
  await verifyGround()
  await writeFile(join(output, 'catalog.next.json'), JSON.stringify({ version: 1, source: manifest.href, regions: [...regionGroups.values()].flat() }))
  await rename(join(output, 'catalog.next.json'), join(output, 'catalog.json'))
}
const bounds = (z: number, x: number, y: number) => {
  const n = 2 ** z, latitude = (v: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * v / n))) * 180 / Math.PI
  return [x / n * 360 - 180, latitude(y + 1), (x + 1) / n * 360 - 180, latitude(y)]
}
for (let x = minX; x <= maxX; x++) for (let y = minY; y <= maxY; y++) {
  const regionKey = `14/${x}/${y}`
  if (regionFilter && !regionFilter.has(regionKey)) continue
  const existingRows = regionGroups.get(regionKey) ?? [], existingRegion = existingRows.at(-1)
  if (args.includes('--resume') && existingRows.length === 1 && existingRegion && (composedMetadata || preciseMetadata || !existingRegion.coverage || existingRegion.coverage.length === 16)
    && existingRegion.meshRevision === BUILDING_MESH_REVISION
    && (composedMetadata ? existingRegion.groundPolicy === COMPOSED_GROUND_POLICY && existingRegion.groundRevision === groundRevision
      : preciseMetadata ? canResumeLayeredGround(existingRegion, groundRevision!)
      : !refreshGround || canResumeGround(existingRegion, groundRevision!))
    && await regionAssetsComplete(output, existingRegion)) continue
  const disk = await statfs(assetOutput)
  if (disk.bavail * disk.bsize < (composedMetadata ? 20 : 8) * 1024 ** 3) throw new Error('Prepared building storage reserve reached')
  const leaves = new Map<string, Footprint[]>(), all: Footprint[] = []
  for (let dx = 0; dx < 4; dx++) for (let dy = 0; dy < 4; dy++) {
    const tx = x * 4 + dx, ty = y * 4 + dy, key = `16/${tx}/${ty}`
    const data = await archive.getZxy(16, tx, ty)
    const features = data ? await decodeBuildings(new Uint8Array(data.data), { z: 16, x: tx, y: ty, key }, Pbf, VectorTile) : []
    leaves.set(key, features); all.push(...features)
  }
  const published = mergePublishedFootprints(await Promise.all(existingRows.map(async row =>
    JSON.parse(await readFile(join(output, row.id, 'footprints.json'), 'utf8')) as Footprint[])))
  let retainedPublished = 0
  try { retainedPublished = preciseMetadata || composedMetadata ? retainPublishedKeys(leaves, published) : 0 }
  catch (error) { throw new Error(`Retaining region 14/${x}/${y} from ${existingRegion?.id}, leaves ${[...leaves.keys()].join(',')}: ${error}`) }
  if (retainedPublished) {
    all.length = 0; all.push(...[...leaves.values()].flat())
  }
  if (!all.length) continue
  const layered = composedMetadata ? await enrichComposedGround(all, {
    revision: composedMetadata.source.fileSignature, sample: points => sampleRaster(composedPath!, points), verify: verifyGround,
  }, fallback!) : preciseMetadata ? await enrichLayeredGround(all, {
    ...(groundMetadata ? { base: { revision: groundMetadata.source.fileSignature, sample: sampleGround,
      verify: () => verifyDemFiles(groundMetadata.revisionFiles || []) } } : {}),
    precise: { revision: preciseMetadata.source.fileSignature, sample: samplePrecise,
      verify: () => verifyDemFiles(preciseMetadata.revisionFiles || []) },
  }) : undefined
  const metric = layered ? { key: `14/${x}/${y}`, status: 'sampled' as 'sampled' | 'published' | 'preserved-previous' | 'no-ground', ...layered.metrics } : undefined
  if (metric) groundMetrics.push(metric)
  const groundSource = layered ? { ...layered, assignments: undefined,
    retainedPublishedKeys: retainedPublished, previousRegions: existingRows.map(row => row.id) }
    : groundRevision ? await enrichGround(all, groundRevision, sampleGround) : undefined
  const missing = all.filter(f => !Number.isFinite(f.z)).length
  const selected = selectGroundLeaves(leaves), { coverage, partialCoverage } = selected
  if (missing) {
    missingRegions.push({ key: `14/${x}/${y}`, buildings: all.length, missingDatum: missing })
    console.error(`Incomplete 14/${x}/${y}: ${missing}/${all.length} buildings have no ground datum`)
  }
  all.length = 0
  all.push(...selected.all)
  for (const [key, features] of selected.leaves) leaves.set(key, features)
  if (!all.length) { if (metric) metric.status = 'no-ground'; continue }
  if (existingRows.some(row => !preservesCoverage(row, coverage))) {
    if (metric) metric.status = 'preserved-previous'
    console.error(`Keeping previous 14/${x}/${y}: updated DEM has incomplete ground coverage`)
    continue
  }
  if (existingRegion) {
    const readyKeys = new Set(all.map(f => f.key))
    if (published.some(f => !readyKeys.has(f.key))) {
      if (metric) metric.status = 'preserved-previous'
      console.error(`Keeping previous 14/${x}/${y}: updated ground would remove published buildings`)
      continue
    }
  }
  const box = bounds(14, x, y), origin = frame((box[0]! + box[2]!) / 2, (box[1]! + box[3]!) / 2)
  const publicationBounds = all.reduce((a, f) => {
    const b = meshFootprintBounds(f)
    return [Math.min(a[0]!, b[0]), Math.min(a[1]!, b[1]), Math.max(a[2]!, b[2]), Math.max(a[3]!, b[3])]
  }, box)
  const digest = createHash('sha256').update(BUILDING_MESH_REVISION).update('partial-ground').update(groundSource ? groundRevision! : 'archive').update(JSON.stringify(coverage)).update(JSON.stringify(all)).digest('hex').slice(0, 12)
  const { id, folder } = await createUnpublishedRegionFolder(assetOutput, `14-${x}-${y}-${digest}`)
  const node = async (z: number, tx: number, ty: number, features: Footprint[], children: any[]) => {
    const b = features.reduce((a, f) => { const r = meshFootprintBounds(f); return [Math.min(a[0]!, r[0]), Math.min(a[1]!, r[1]), Math.max(a[2]!, r[2]), Math.max(a[3]!, r[3])] }, [Infinity, Infinity, -Infinity, -Infinity])
    const region = b.map(v => v * Math.PI / 180).concat([Math.min(-12, ...features.map(f => f.z! - 12)), Math.max(...features.map(f => f.z! + f.h)) + 1])
    const coarse = z < 16, uri = `${z}-${tx}-${ty}.b3dm`
    await writeFile(join(folder, uri), bakeMesh(features, origin, coarse))
    // Bounding-box proxy differs by at most its horizontal diagonal from its source footprint.
    const error = coarse ? Math.max(...features.map(f => { const b = meshFootprintBounds(f); return Math.hypot((b[2] - b[0]) * 111320 * Math.cos(lat * Math.PI / 180), (b[3] - b[1]) * 111320) })) : 0
    return { boundingVolume: { region }, geometricError: error * (z === 14 ? 2 : 1), refine: 'REPLACE', content: { uri }, ...(children.length ? { children } : {}) }
  }
  const mid = []
  for (let dx = 0; dx < 2; dx++) for (let dy = 0; dy < 2; dy++) {
    const mx = x * 2 + dx, my = y * 2 + dy, children = [], group: Footprint[] = []
    for (let a = 0; a < 2; a++) for (let b = 0; b < 2; b++) {
      const fx = mx * 2 + a, fy = my * 2 + b, features = leaves.get(`16/${fx}/${fy}`)!
      if (!features.length) continue
      group.push(...features); children.push(await node(16, fx, fy, features, []))
    }
    if (group.length) mid.push(await node(15, mx, my, group, children))
  }
  const root = await node(14, x, y, all, mid)
  await writeFile(join(folder, 'tileset.json'), JSON.stringify({ asset: { version: '1.0', tilesetVersion: digest }, geometricError: root.geometricError * 2, root: { ...root, transform: origin.transform } }))
  await writeFile(join(folder, 'footprints.json'), JSON.stringify(all))
  if (groundSource) await writeFile(join(folder, 'ground-source.json'), JSON.stringify(groundSource))
  if (assetOutput !== output) {
    try { await symlink(folder, join(output, id), 'junction') } catch (error: any) {
      if (error.code !== 'EEXIST' || await realpath(join(output, id)) !== await realpath(folder)) throw error
    }
  }
  const counts = { measured: all.filter(f => f.s === 'm').length, estimated: all.filter(f => f.s === 'e').length, unknown: all.filter(f => f.s === 'u').length }
  regionGroups.set(regionKey, [{ meshRevision: BUILDING_MESH_REVISION, groundPolicy: layered ? layered.policy : groundSource ? 'local-dem' : 'archive',
    ...(layered ? { groundMetrics: layered.metrics } : {}),
    ...(groundSource ? { groundRevision, groundSource: `/world-buildings/${id}/ground-source.json` } : {}), id, z: 14, x, y, bounds: publicationBounds, coverage, partialCoverage, url: `/world-buildings/${id}/tileset.json`, footprints: `/world-buildings/${id}/footprints.json`, counts }])
  await publish()
  if (metric) metric.status = 'published'
  console.log(`${id}: ${all.length} buildings; ${mid.length} intermediate tiles; ${leaves.size} detailed tiles`)
}
console.log(`Catalog: ${[...regionGroups.values()].flat().length} regions`)
await writeFile(join(output, 'last-bake-report.json'), JSON.stringify({ source: manifest.href,
  ...(preciseMetadata || composedMetadata ? { groundMetricBaseline: 'decoded PMTiles plus retained published keys; recovery totals require the frozen missing-key reconciliation',
    groundMetricUnit: 'decoded footprint records (tile duplicates are not deduplicated)', groundMetrics,
    groundTotals: groundMetrics.reduce((total, row) => ({ beforeMissing: total.beforeMissing + row.beforeMissing,
      newlyFilled: total.newlyFilled + row.newlyFilled, preciseOverride: total.preciseOverride + row.preciseOverride,
      remaining: total.remaining + row.remaining }), { beforeMissing: 0, newlyFilled: 0, preciseOverride: 0, remaining: 0 }),
    groundRevision } : {}),
  bounds: [west, south, east, north], ...(regionFilter ? { regionFilter: [...regionFilter] } : {}), missingRegions }, null, 2))
if (missingRegions.length) process.exitCode = 2

await localArchive?.close()
