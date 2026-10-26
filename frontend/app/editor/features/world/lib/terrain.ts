/**
 * Terrain from SiteContext's NGII DEM, as a Cesium heightmap terrain. Static archive tiles supply a 33 x 33 grid;
 * installations without an archive retain the published-JSON/computation path.
 * (rows north to south). A tile the DEM cannot answer is filled from the nearest coarser tile it did answer
 * (the same DEM, sampled wider) — filling it flat at the fallback height cut 60-100 m cliffs into the ground and hung
 * masses on their edges. Far-away tiles (coarser than MIN_LEVEL) and tiles with no answered ancestor stand flat at the
 * fallback height, never as a hole or a made-up slope.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { readSceneCache, writeSceneCache } from './scene-cache'
import { createPublishedTerrainReader } from './published-terrain'
import { defaultTerrainArchiveReader, type ArchivedTerrain } from './terrain-archive'
import { readTerrainRevision, type TerrainRevision } from './terrain-revision'
import type { createTerrainHeightContract, ResolvedTerrainGrid } from './terrain-height-contract'
import { defaultTerrainPublicationReader } from './terrain-publication'
const SIZE = 33
const MIN_LEVEL = 11   // 0.0879 degree tiles fit the backend's 0.1 degree limit.
const MAX_LEVEL = 17   // ~4.8 m between samples matches the source DEM's 5 m grid.
// At most this many tile requests at once: the browser has ~6 connections per host and the context layers need some.
const IN_FLIGHT = 2
const KOREA = { west: 124, south: 33, east: 132, north: 39 }
const KEEP = 2000      // ~4.3 kB per answered tile

async function awaitArchiveConsumer<T>(read: () => Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) throw new Error('terrain request retired')
  let abort!: () => void
  const retired = new Promise<never>((_resolve, reject) => {
    abort = () => reject(new Error('terrain request retired'))
    signal.addEventListener('abort', abort, { once: true })
  })
  try {
    // Retire this provider's wait, not the shared archive's wire request/cache.
    return await Promise.race([Promise.resolve().then(() => {
      if (signal.aborted) throw new Error('terrain request retired')
      return read()
    }), retired])
  } finally { signal.removeEventListener('abort', abort) }
}

/** The heights of tile (x, y, level) read off an answered ancestor tile, bilinear; null when no ancestor answered. */
function fromAncestor(answered: Map<string, Float32Array>, x: number, y: number, level: number): Float32Array | null {
  for (let d = 1; level - d >= MIN_LEVEL; d++) {
    const ax = x >> d, ay = y >> d, h = answered.get(`${level - d}/${ax}/${ay}`)
    if (!h) continue
    const n = 2 ** d, ox = x - ax * n, oy = y - ay * n, out = new Float32Array(SIZE * SIZE), last = SIZE - 1
    for (let j = 0; j < SIZE; j++) {
      for (let i = 0; i < SIZE; i++) {
        const fx = ((ox + i / last) / n) * last, fy = ((oy + j / last) / n) * last
        const c = Math.min(Math.floor(fx), last - 1), r = Math.min(Math.floor(fy), last - 1), u = fx - c, v = fy - r
        out[j * SIZE + i] = h[r * SIZE + c]! * (1 - u) * (1 - v) + h[r * SIZE + c + 1]! * u * (1 - v)
          + h[(r + 1) * SIZE + c]! * (1 - u) * v + h[(r + 1) * SIZE + c + 1]! * u * v
      }
    }
    return out
  }
  return null
}

/** `focus`: where the camera looks. A tile takes 5-12 s and Cesium asks for tiles out to the horizon, so waiting
 *  tiles are served nearest to the focus first — in arrival order the ground under the camera waited for minutes. */
export function demTerrain(Cesium: any, fallback: () => number, focus: () => { lon: number; lat: number } | null = () => null,
  onError: (message: string) => void = () => {}, published: ReturnType<typeof createPublishedTerrainReader> | undefined = undefined,
  revisionReader: () => Promise<TerrainRevision | null> = readTerrainRevision, onSnapshot: (version: string) => void = () => {},
  archive: ((key: string) => Promise<ArchivedTerrain | null | undefined>) | undefined = published ? undefined : defaultTerrainArchiveReader,
  resolved?: ReturnType<typeof createTerrainHeightContract>, publicationReader = defaultTerrainPublicationReader): any {
  if (resolved && resolved.size !== SIZE) throw new Error('Terrain provider requires a 33 x 33 contract grid')
  const readPublished = published ?? createPublishedTerrainReader(undefined, undefined, onSnapshot)
  // Sparse extra levels reduce reprojection error around repaired ground points;
  // they do not claim finer survey resolution than the original five metre DEM.
  let maxLevel = resolved?.maxLevel ?? (archive ? 20 : MAX_LEVEL)
  const autoContract = !resolved && !published && archive === defaultTerrainArchiveReader
  let contractChecked = !autoContract, preparation: Promise<typeof resolved> | undefined
  const prepareContract = () => preparation ??= (autoContract ? publicationReader() : Promise.resolve(resolved))
    .then(value => {
      if (value && value.size !== SIZE) throw new Error('Terrain provider requires a 33 x 33 contract grid')
      resolved = value; contractChecked = true
      if (value) { maxLevel = value.maxLevel; provider.sampleHeightDetails = sampleHeightDetails }
      return value
    }).catch(error => { preparation = undefined; throw error })
  let revision: Promise<TerrainRevision | null> | undefined
  let running = 0
  let checkingDisplayCache = 0
  let disposed = false
  const controller = new AbortController()
  const consumers = new Map<string, { display: boolean; needed: Set<() => boolean>; controller: AbortController }>()
  const waiting: { key: string; lon: number; lat: number; priority: boolean; go: () => void }[] = []
  const slot = (key: string, lon: number, lat: number, priority: boolean, signal: AbortSignal) => new Promise<void>((go, reject) => {
    if (signal.aborted) { reject(new Error('terrain request retired')); return }
    if (running < IN_FLIGHT) { running++; go(); return }
    const cancel = () => {
      const index = waiting.indexOf(queued)
      if (index >= 0) waiting.splice(index, 1)
      signal.removeEventListener('abort', cancel)
      reject(new Error('terrain request retired'))
    }
    const queued = { key, lon, lat, priority, go: () => { signal.removeEventListener('abort', cancel); running++; go() } }
    waiting.push(queued)
    signal.addEventListener('abort', cancel, { once: true })
  })
  const release = () => {
    running--
    if (!waiting.length) return
    let f: { lon: number; lat: number } | null = null
    // never let the camera lookup stop the queue: a destroyed viewer throws, and waiting tiles would never start
    try { f = disposed ? null : focus() } catch { f = null }
    let best = waiting.findIndex(w => w.priority)
    const urgent = best >= 0
    if (!urgent) best = 0
    if (f) {
      const d = (w: { lon: number; lat: number }) => ((w.lon - f.lon) * Math.cos((f.lat * Math.PI) / 180)) ** 2 + (w.lat - f.lat) ** 2
      // A new zoom target must not wait behind height samples queued for the old
      // overview. Preserve measured priority, but rank within it by CURRENT focus.
      waiting.forEach((w, i) => { if ((!urgent || w.priority) && d(w) < d(waiting[best]!)) best = i })
    }
    waiting.splice(best, 1)[0]!.go()
  }
  const flat = () => new Float32Array(SIZE * SIZE).fill(resolved ? 0 : fallback())
  const answered = new Map<string, Float32Array>()
  // Keep missing source cells separate from the finite grid needed for rendering.
  const measured = new Map<string, Float32Array>()
  const details = new Map<string, ResolvedTerrainGrid>()
  let lastPrimeAt = -Infinity
  const pending = new Map<string, Promise<Float32Array>>()
  const urgentKeys = new Set<string>()
  const keep = (key: string, h: Float32Array) => {
    answered.set(key, h)
    if (answered.size > KEEP) { const oldest = answered.keys().next().value!; answered.delete(oldest); measured.delete(oldest); details.delete(oldest) }
    return h
  }
  // a gateway hiccup (502/504, dropped connection) is asked once more; a refusal (the DEM does not reach) is not
  const ask = (query: URLSearchParams, again: boolean, signal: AbortSignal): Promise<Float32Array> =>
    (disposed ? Promise.reject(new Error('terrain replaced')) : fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/terrain-heights?${query}`,
      { signal: AbortSignal.any([controller.signal, signal, AbortSignal.timeout(15_000)]) }))
      .then((res: Response) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body) => (Array.isArray(body.heights) && body.heights.length === SIZE * SIZE && body.heights.every(Number.isFinite)
        ? new Float32Array(body.heights) : Promise.reject(new Error('no valid heights'))))
      .catch((e: Error) => (again && !disposed && !signal.aborted && (/^5\d\d$/.test(e.message) || e instanceof TypeError) ? ask(query, false, signal) : Promise.reject(e)))
  const readTile = (x: number, y: number, level: number, priority = false, needed: () => boolean = () => true): Float32Array | Promise<Float32Array> | undefined => {
      if (level > maxLevel) return undefined
      if (contractChecked && level < (resolved?.minLevel ?? MIN_LEVEL)) return flat()
      const r = provider.tilingScheme.tileXYToRectangle(x, y, level)
      const [west, south, east, north] = [r.west, r.south, r.east, r.north].map((v: number) => Cesium.Math.toDegrees(v))
      const outside = west < KOREA.west || east > KOREA.east || south < KOREA.south || north > KOREA.north
      if (outside && contractChecked) return flat()
      const query = new URLSearchParams({ west: String(west), south: String(south), east: String(east), north: String(north), size: String(SIZE) })
      const key = `${level}/${x}/${y}`
      const cached = answered.get(key)
      if (cached) return cached
      if (pending.has(key)) {
        const users = consumers.get(key)!
        if (users.controller.signal.aborted) {
          // A camera can return before abort cleanup finishes. Join a fresh job,
          // not the cancelled result from its previous visit.
          return priority ? pending.get(key)!.catch(() => undefined).then(() => readTile(x, y, level, true, needed)!) : undefined
        }
        if (priority) users.needed.add(needed)
        else users.display = true
        if (priority) {
          urgentKeys.add(key)
          const queued = waiting.find(request => request.key === key)
          if (queued) queued.priority = true
        }
        return pending.get(key)
      }
      // Return control to Cesium's view-prioritized scheduler instead of retaining
      // a backlog of display tiles from old cameras. Undefined means retry later,
      // keeping the parent visible; measured camera/building samples still queue.
      if (!priority && running + checkingDisplayCache >= (archive ? 8 : IN_FLIGHT)) return undefined
      const users = { display: !priority, needed: new Set(priority ? [needed] : []), controller: new AbortController() }
      consumers.set(key, users)
      let acquired = false
      let checking = !priority
      if (checking) checkingDisplayCache++
      const finishCheck = () => { if (checking) { checkingDisplayCache--; checking = false } }
      const request = Promise.resolve()
        .then(async () => {
          if (disposed || users.controller.signal.aborted) throw new Error('terrain request retired')
          if (autoContract) await awaitArchiveConsumer(prepareContract, users.controller.signal)
          if (outside || level < (resolved?.minLevel ?? MIN_LEVEL)) return flat()
          if (resolved) {
            if (level < resolved.minLevel) return flat()
            const grid = await awaitArchiveConsumer(() => resolved!.resolve({ level, x, y }), users.controller.signal)
            if (disposed || users.controller.signal.aborted) throw new Error('terrain request retired')
            measured.set(key, grid.heights)
            details.set(key, grid)
            return grid.heights
          }
          if (archive) {
            const baked = await awaitArchiveConsumer(() => archive(key), users.controller.signal)
            if (disposed || users.controller.signal.aborted) throw new Error('terrain request retired')
            if (baked) {
              measured.set(key, baked.heights)
              if (baked.heights.every(Number.isFinite)) return baked.heights
              const parent = fromAncestor(answered, x, y, level)
              const display = baked.heights.map((height, i) => Number.isFinite(height) ? height : parent?.[i] ?? fallback())
              return display
            }
            if (baked === null) throw new Error('no measured terrain coverage')
          }
          const source = await (revision ??= revisionReader().catch(() => null))
          const cacheKey = source ? `${source.revision}/${key}` : null
          const saved = cacheKey ? await readSceneCache<number[]>('terrain', cacheKey, 24 * 60 * 60_000) : undefined
          if (disposed || users.controller.signal.aborted) throw new Error('terrain request retired')
          if (saved?.length === SIZE * SIZE && saved.every(Number.isFinite)) return new Float32Array(saved)
          finishCheck()
          await slot(key, (west + east) / 2, (south + north) / 2, priority || urgentKeys.has(key), users.controller.signal)
          acquired = true
          if (disposed || users.controller.signal.aborted) throw new Error('terrain request retired')
          // Published tiles are network work too; only the local browser cache
          // bypasses admission, otherwise an overview floods the connection pool.
          const baked = await readPublished(key, source?.vrt_sha256 ?? '')
          if (disposed || users.controller.signal.aborted) throw new Error('terrain request retired')
          if (baked) return baked
          const data = await ask(query, true, users.controller.signal)
          if (cacheKey) void writeSceneCache('terrain', cacheKey, Array.from(data), KEEP)
          return data
        })
        .then((h) => keep(key, h))
        .catch((error: Error) => {
          if (resolved || (autoContract && !contractChecked)) {
            if (!disposed && !users.controller.signal.aborted) onError(`지형을 불러오지 못했습니다 (${error.message}). 다시 시도합니다`)
            throw error
          }
          if (!disposed && !users.controller.signal.aborted) onError(`지형 일부를 불러오지 못했습니다 (${error.message}). 임시 지형 표시 중`)
          return fromAncestor(answered, x, y, level) ?? flat()
        })
        .finally(() => { finishCheck(); pending.delete(key); consumers.delete(key); urgentKeys.delete(key); if (acquired) release() })
      pending.set(key, request)
      return request
  }
  const provider = new Cesium.CustomHeightmapTerrainProvider({ width: SIZE, height: SIZE, callback: readTile })
  // Undefined callback results mean "retry later", not "no finer source".
  // Without a finite availability limit, finer levels remain in the load queue.
  // Sparse archive detail reduces reprojection error, not the DEM's survey resolution.
  provider.getTileDataAvailable = (_x: number, _y: number, level: number) => level <= maxLevel
  provider.pruneRequests = () => {
    for (const users of consumers.values()) {
      if (!users.display && ![...users.needed].some(needed => needed())) users.controller.abort()
    }
  }
  let preparationSerial = 0
  provider.sampleHeight = async (lon: number, lat: number, needed: () => boolean = () => true): Promise<number> => {
    if (disposed || !Number.isFinite(lon) || !Number.isFinite(lat)) throw new Error('terrain unavailable')
    if (autoContract && !contractChecked) {
      const key = `prepare/${++preparationSerial}`
      const users = { display: false, needed: new Set([needed]), controller: new AbortController() }
      consumers.set(key, users)
      try { await awaitArchiveConsumer(prepareContract, users.controller.signal) }
      catch (error) { if (disposed || !needed()) throw new Error('terrain sample retired'); throw error }
      finally { consumers.delete(key) }
    }
    if (resolved && (lon < -180 || lon > 180 || lat < -90 || lat > 90)) throw new Error('outside terrain coverage')
    const width = 180 / 2 ** maxLevel
    const position = resolved ? { longitude: lon, latitude: lat } : Cesium.Cartographic.fromDegrees(lon, lat)
    const tile = resolved ? { x: Math.min(2 ** (maxLevel+1)-1,Math.floor((lon+180)/width)), y: Math.min(2 ** maxLevel-1,Math.floor((90-lat)/width)) }
      : provider.tilingScheme.positionToTileXY(position, maxLevel)
    if (!tile) throw new Error('outside terrain coverage')
    if (!needed()) throw new Error('terrain sample retired')
    // Camera placement knows its destination before globe traversal reaches it.
    // Warm its parent chain concurrently so refinement does not serialize HTTP.
    const requested = readTile(tile.x, tile.y, maxLevel, true, needed)
    if (archive && !resolved && Date.now() - lastPrimeAt > 1500) {
      lastPrimeAt = Date.now()
      for (let level = MIN_LEVEL; level < maxLevel; level++) {
        const shift = maxLevel - level
        void Promise.resolve(readTile(tile.x >> shift, tile.y >> shift, level, true, needed)).catch(() => {})
      }
    }
    try { await requested }
    catch (error) { if (disposed || !needed()) throw new Error('terrain sample retired'); throw error }
    if (!needed()) throw new Error('terrain sample retired')
    const data = measured.get(`${maxLevel}/${tile.x}/${tile.y}`) ?? answered.get(`${maxLevel}/${tile.x}/${tile.y}`)
    if (disposed || !data) throw new Error('no measured terrain height')
    const r = provider.tilingScheme.tileXYToRectangle(tile.x, tile.y, maxLevel)
    const last = SIZE - 1
    const x = Math.max(0, Math.min(last, resolved ? (lon+180-tile.x*width)/width*last : (position.longitude-r.west)/(r.east-r.west)*last))
    const y = Math.max(0, Math.min(last, resolved ? (90-lat-tile.y*width)/width*last : (r.north-position.latitude)/(r.north-r.south)*last))
    const c = Math.min(Math.floor(x), last - 1), row = Math.min(Math.floor(y), last - 1), u = x - c, v = y - row
    if (![data[row * SIZE + c], data[row * SIZE + c + 1], data[(row + 1) * SIZE + c], data[(row + 1) * SIZE + c + 1]].every(Number.isFinite)) {
      // Renormalize valid bilinear contributors at a NoData edge. An exact
      // missing vertex still has zero support and must not become a datum.
      const values = [data[row * SIZE + c]!, data[row * SIZE + c + 1]!, data[(row + 1) * SIZE + c]!, data[(row + 1) * SIZE + c + 1]!]
      const weights = [(1-u)*(1-v),u*(1-v),(1-u)*v,u*v]
      let total = 0, value = 0
      values.forEach((height, i) => { if (Number.isFinite(height)) { total += weights[i]!; value += height * weights[i]! } })
      if (total <= 1e-12) throw new Error('no measured terrain height')
      return value / total
    }
    return data[row * SIZE + c]! * (1 - u) * (1 - v) + data[row * SIZE + c + 1]! * u * (1 - v)
      + data[(row + 1) * SIZE + c]! * (1 - u) * v + data[(row + 1) * SIZE + c + 1]! * u * v
  }
  // replaced or unmounted: queued tiles resolve flat without fetching
  const sampleHeightDetails = async (lon: number, lat: number, needed: () => boolean = () => true) => {
    if (disposed) throw new Error('terrain unavailable')
    const height = await provider.sampleHeight(lon, lat, needed)
    if (!resolved) throw new Error('Terrain publication has no height contract')
    const width=180/2**maxLevel
    const tile={x:Math.min(2**(maxLevel+1)-1,Math.floor((lon+180)/width)),y:Math.min(2**maxLevel-1,Math.floor((90-lat)/width))}
    const grid = tile && details.get(`${maxLevel}/${tile.x}/${tile.y}`)
    if (!grid || grid.archiveSha256 !== resolved.identity.split('/')[0]) throw new Error('Terrain publication details unavailable')
    const last=SIZE-1
    const x = Math.max(0, Math.min(last, (lon+180-tile.x*width)/width*last))
    const y = Math.max(0, Math.min(last, (90-lat-tile.y*width)/width*last))
    const col = Math.min(last-1,Math.floor(x)), row = Math.min(last-1,Math.floor(y)), u=x-col,v=y-row
    const indices=[row*SIZE+col,row*SIZE+col+1,(row+1)*SIZE+col,(row+1)*SIZE+col+1]
    const weights=[(1-u)*(1-v),u*(1-v),(1-u)*v,u*v]
    const sourceLevels=[...new Set(indices.filter((_,i)=>weights[i]!>0).map(i=>grid.sourceLevels[i]!))].sort((a,b)=>a-b)
    const value = {height,sourceLevels,ellipsoidZero:sourceLevels.includes(-1),archiveSha256:grid.archiveSha256,contract:grid.contract}
    if (disposed || !needed()) throw new Error('terrain sample retired')
    return value
  }
  if (resolved) provider.sampleHeightDetails = sampleHeightDetails
  provider.dispose = () => { disposed = true; controller.abort(); for (const users of consumers.values()) users.controller.abort() }
  return provider
}
