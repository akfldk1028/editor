import { PMTiles } from 'pmtiles'
import { mapAssetUrl } from './map-asset-url'
import { defaultMapReleaseReader } from './map-release'

type Archive = { getMetadata(): Promise<unknown>; getZxy(z: number, x: number, y: number): Promise<{ data: ArrayBuffer } | undefined> }
type Metadata = { schema: string; size: number; grid: string; archiveZoomOffset: number; minLevel: number; maxLevel: number; vrt_sha256: string; bounds?: [number, number, number, number] }
export type ArchivedTerrain = { heights: Float32Array; sourceLevel: number; revision: string }

export function decodeHeightTile(buffer: ArrayBuffer): Float32Array {
  const view = new DataView(buffer)
  if (buffer.byteLength !== 4364 || view.getUint32(0, true) !== 0x314d5448 || view.getUint16(4, true) !== 33) throw new Error('invalid terrain tile')
  const result = new Float32Array(1089)
  for (let i = 0; i < result.length; i++) {
    const value = view.getFloat32(8 + i * 4, true)
    if (!Number.isNaN(value) && (!Number.isFinite(value) || value < -500 || value > 9000)) throw new Error('invalid terrain height')
    result[i] = value
  }
  return result
}

function resample(parent: Float32Array, x: number, y: number): Float32Array {
  const result = new Float32Array(1089)
  for (let row = 0; row < 33; row++) for (let col = 0; col < 33; col++) {
    const fx = (x % 2) * 16 + col / 2, fy = (y % 2) * 16 + row / 2
    const c = Math.min(31, Math.floor(fx)), r = Math.min(31, Math.floor(fy)), u = fx - c, v = fy - r
    const corners = [parent[r*33+c]!,parent[r*33+c+1]!,parent[(r+1)*33+c]!,parent[(r+1)*33+c+1]!]
    result[row*33+col] = corners.every(Number.isFinite)
      ? corners[0]!*(1-u)*(1-v)+corners[1]!*u*(1-v)+corners[2]!*(1-u)*v+corners[3]!*u*v
      : parent[Math.round(fy)*33+Math.round(fx)]!
  }
  return result
}

export function createTerrainArchiveReader(
  url = process.env.NEXT_PUBLIC_TERRAIN_ARCHIVE_URL,
  get: (url: string) => Promise<Response> = url => fetch(url, { signal: AbortSignal.timeout(2000) }),
  factory: (url: string) => Archive = url => new PMTiles(url),
) {
  let source: Promise<{ archive: Archive; metadata: Metadata; url: string; archiveSha256?: string } | undefined> | undefined
  const pending = new Map<string, Promise<ArchivedTerrain | null>>()
  const rawPending = new Map<string, Promise<ArchivedTerrain | null>>()
  const settled = new Map<string, ArchivedTerrain | null>()
  const rawSettled = new Map<string, ArchivedTerrain | null>()
  const remember = (cache: Map<string, ArchivedTerrain | null>, key: string, value: ArchivedTerrain | null) => {
    cache.delete(key); cache.set(key, value)
    if (cache.size > 2000) cache.delete(cache.keys().next().value!)
    return value
  }
  let active = 0
  const queue: (() => void)[] = []
  const requestTile = async (archive: Archive, z: number, x: number, y: number) => {
    if (active >= 8) await new Promise<void>(resolve => queue.push(resolve))
    else active++
    try { return await archive.getZxy(z, x, y) }
    finally { const next = queue.shift(); if (next) next(); else active-- }
  }
  const open = () => source ??= (async () => {
    let href = url, expected: string | undefined, archiveSha256: string | undefined
    if (!href) {
      const release = await defaultMapReleaseReader()
      const response = release ? Response.json(release.terrain) : await get(mapAssetUrl('terrain', 'archive.json'))
      if (response.status === 404) return undefined
      if (!response.ok) throw new Error(`terrain archive manifest ${response.status}`)
      const config = await response.json()
      href = config.url; expected = config.vrt_sha256; archiveSha256 = config.sha256
      if (typeof href === 'string' && !/^https?:\/\//.test(href)) href = mapAssetUrl('terrain', href)
    }
    if (typeof href !== 'string' || !/^(https?:\/\/|\/[^/])/.test(href) || !/\.pmtiles(?:[?#]|$)/.test(href)) throw new Error('invalid terrain archive URL')
    const archive = factory(href), metadata = await archive.getMetadata() as Metadata
    if (metadata?.schema !== 'ngii-heightmap-v1' || metadata.grid !== 'Cesium.GeographicTilingScheme' || metadata.size !== 33
      || metadata.archiveZoomOffset !== 1 || !/^[a-f0-9]{64}$/.test(metadata.vrt_sha256)
      || !Number.isInteger(metadata.minLevel) || !Number.isInteger(metadata.maxLevel) || metadata.minLevel < 0 || metadata.maxLevel > 20
      || metadata.maxLevel < metadata.minLevel || (expected && expected !== metadata.vrt_sha256)) throw new Error('invalid terrain archive metadata')
    return { archive, metadata, url: href, archiveSha256 }
  })().catch(error => { source = undefined; throw error })
  const read = async (key: string): Promise<ArchivedTerrain | null | undefined> => {
    if (!/^\d+\/\d+\/\d+$/.test(key)) return undefined
    const ready = await open()
    if (!ready) return undefined
    const [level,x,y] = key.split('/').map(Number) as [number,number,number]
    // A regional staging archive must not disable existing terrain elsewhere.
    if (ready.metadata.bounds) {
      const [w,s,e,n] = ready.metadata.bounds, width = 180 / 2**level
      const west = x * width - 180, north = 90 - y * width
      if (west >= e || west + width <= w || north <= s || north - width >= n) return undefined
    }
    if (level < ready.metadata.minLevel || level > 20 || x >= 2**(level+1) || y >= 2**level) return null
    if (settled.has(key)) return remember(settled, key, settled.get(key)!)
    if (!pending.has(key)) {
      const job = (async (): Promise<ArchivedTerrain | null> => {
        const tile = level <= ready.metadata.maxLevel ? await requestTile(ready.archive,level+1,x,y) : undefined
        if (tile) return { heights: decodeHeightTile(tile.data), sourceLevel: level, revision: ready.metadata.vrt_sha256 }
        if (level <= ready.metadata.minLevel) return null
        const parent = await read(`${level-1}/${Math.floor(x/2)}/${Math.floor(y/2)}`)
        return parent ? { ...parent, heights: resample(parent.heights,x,y) } : null
      })().then(value => remember(settled, key, value)).finally(() => {
        if (pending.get(key) === job) pending.delete(key)
      })
      pending.set(key,job)
    }
    return pending.get(key)!
  }
  // The shared height contract needs confirmed raw absence/NoData, not this
  // legacy reader's implicit parent interpolation. Exceptions remain retryable.
  const raw = async (key: string): Promise<ArchivedTerrain | null | undefined> => {
    if (!/^\d+\/\d+\/\d+$/.test(key)) throw new Error('invalid raw terrain key')
    const ready = await open()
    if (!ready) return undefined
    const [level, x, y] = key.split('/').map(Number) as [number, number, number]
    if (level < ready.metadata.minLevel || level > 20 || x >= 2 ** (level + 1) || y >= 2 ** level) throw new Error('outside raw terrain grid')
    if (ready.metadata.bounds) {
      const [w,s,e,n] = ready.metadata.bounds, width = 180 / 2 ** level
      const west = x * width - 180, north = 90 - y * width
      if (west >= e || west + width <= w || north <= s || north - width >= n) throw new Error('outside raw terrain archive bounds')
    }
    if (rawSettled.has(key)) return remember(rawSettled, key, rawSettled.get(key)!)
    if (!rawPending.has(key)) {
      const job = (async () => {
        const tile = level <= ready.metadata.maxLevel ? await requestTile(ready.archive, level + 1, x, y) : undefined
        return tile ? { heights: decodeHeightTile(tile.data), sourceLevel: level, revision: ready.metadata.vrt_sha256 } : null
      })().then(value => remember(rawSettled, key, value)).finally(() => {
        if (rawPending.get(key) === job) rawPending.delete(key)
      })
      rawPending.set(key, job)
    }
    return rawPending.get(key)!
  }
  return Object.assign(read, { prepare: open, raw })
}

// Start the tiny manifest/index lookup while the Cesium bundle is loading.
// The immutable archive and its decoded tiles can be shared by recreated viewers.
export const defaultTerrainArchiveReader = createTerrainArchiveReader()
if (typeof window !== 'undefined') void defaultTerrainArchiveReader.prepare().catch(() => {})
