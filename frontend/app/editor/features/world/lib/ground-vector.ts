import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { PMTiles, ResolvedValueCache, TileType, type Header, type Source } from 'pmtiles'
import { groundParallel, groundRangeSource, type GroundImageryLayer } from './ground-imagery'

/** Near ground drawn from z14 vector tiles (tools/bake-ground-vector-tiles.py) at the requested level's own resolution. */
export type GroundVectorLayer = { url: string; sha256: string; bounds: [number, number, number, number]; level: number; credit: string }
type Archive = { getHeader(): Promise<{ tileType: number; minZoom: number; maxZoom: number; minLon: number; minLat: number; maxLon: number; maxLat: number }>
  getZxy(z: number, x: number, y: number, signal?: AbortSignal): Promise<{ data: ArrayBuffer } | undefined> }
type Shape = { path: Path2D; box: [number, number, number, number]; c: number }
type Decoded = { extent: number; landcover: Shape[]; roads: Shape[] }
type Dependencies = { get?: (url: string, init?: RequestInit) => Promise<Response>; archive?: (source: Source) => Archive; canvas?: () => HTMLCanvasElement }

// egis-lv3-2025-diagram.sld rule order, matching the bake's class index; roads match the road pyramid's colour.
export const LANDCOVER_COLOURS = ['#cfdcc0', '#dfe8d1', '#ece9da', '#efe9de', '#d3e2ec', '#e2e1dc', '#d0d0cc']
const ROAD_COLOUR = 'rgb(206,205,199)'
const ROAD_EDGE = 'rgb(168,167,160)'
export const VECTOR_MAX_LEVEL = 21
/** First level drawn from vectors: two above the archive level, merging up to 4x4 archive tiles per request. */
export const VECTOR_MIN_LEVEL = (archiveLevel: number) => archiveLevel - 2
const TILE = 256

export function validateGroundVector(value: unknown): GroundVectorLayer {
  const layer = value as GroundVectorLayer | null
  if (!layer || Object.keys(layer).sort().join(',') !== 'bounds,credit,level,sha256,url'
    || typeof layer.url !== 'string' || !/^(https?:\/\/|\/[^/])/.test(layer.url) || layer.url.includes('\\')
    || /[?#]/.test(layer.url) || !layer.url.endsWith('.pmtiles') || !/^[a-f0-9]{64}$/.test(layer.sha256)
    || !Array.isArray(layer.bounds) || layer.bounds.length !== 4 || !layer.bounds.every(Number.isFinite)
    || layer.bounds[0] < -180 || layer.bounds[2] > 180 || layer.bounds[1] < -85.05112878 || layer.bounds[3] > 85.05112878
    || layer.bounds[0] >= layer.bounds[2] || layer.bounds[1] >= layer.bounds[3]
    || !Number.isInteger(layer.level) || layer.level < 10 || layer.level > 16
    || typeof layer.credit !== 'string' || !layer.credit.trim() || layer.credit.length > 500) throw Error('Invalid ground vector layer')
  return structuredClone(layer)
}

function decode(data: ArrayBuffer): Decoded {
  const tile = new VectorTile(new Pbf(new Uint8Array(data)))
  let extent = 4096
  const read = (name: string) => {
    const layer = tile.layers[name], shapes: Shape[] = []
    if (!layer) return shapes
    extent = layer.extent
    for (let i = 0; i < layer.length; i++) {
      const feature = layer.feature(i)
      if (feature.type !== 3) continue
      const path = new Path2D(), box: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity]
      for (const ring of feature.loadGeometry()) {
        ring.forEach((p, j) => {
          if (j) path.lineTo(p.x, p.y); else path.moveTo(p.x, p.y)
          if (p.x < box[0]) box[0] = p.x; if (p.y < box[1]) box[1] = p.y
          if (p.x > box[2]) box[2] = p.x; if (p.y > box[3]) box[3] = p.y
        })
        // Close by returning to the first point: Chrome's Path2D.closePath cost grows with the path, which made
        // many-ring landcover features quadratic (9.8 s of main thread on one jump). fill() closes subpaths anyway.
        if (ring.length) path.lineTo(ring[0]!.x, ring[0]!.y)
      }
      shapes.push({ path, box, c: Number(feature.properties.c ?? 0) })
    }
    return shapes
  }
  const landcover = read('landcover'), roads = read('roads')
  return { extent, landcover, roads }
}

/** Give alpha-zero texels their neighbour's colour: Cesium filters unpremultiplied RGBA, and the canvas's black
 * transparent texels would otherwise darken every antialiased edge. Raw RGBA goes to Cesium's Texture directly. */
export function bleed(data: Uint8ClampedArray) {
  const at = (i: number, j: number) => { data[i] = data[j]!; data[i + 1] = data[j + 1]!; data[i + 2] = data[j + 2]! }
  const row = TILE * 4
  for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
    const i = y * row + x * 4
    if (data[i + 3]) continue
    if (x > 0 && data[i - 1]) at(i, i - 4)
    else if (x < TILE - 1 && data[i + 7]) at(i, i + 4)
    else if (y > 0 && data[i - row + 3]) at(i, i - row)
    else if (y < TILE - 1 && data[i + row + 3]) at(i, i + row)
  }
  return { width: TILE, height: TILE, arrayBufferView: new Uint8Array(data.buffer, data.byteOffset, data.byteLength) }
}

/** Two Cesium imagery providers (landcover, roads) over one vector archive: levels level-2..21, transparent below. */
export async function createGroundVectorProviders(C: any, layer: GroundVectorLayer, signal: AbortSignal, dependencies: Dependencies = {}) {
  layer = validateGroundVector(layer)
  const lifetime = new AbortController(), cancel = () => lifetime.abort()
  signal.addEventListener('abort', cancel, { once: true }); if (signal.aborted) cancel()
  const source = groundRangeSource(layer as unknown as GroundImageryLayer, lifetime.signal, dependencies.get)
  const directories = dependencies.archive ? undefined : new ResolvedValueCache(32)
  const archive: Archive = dependencies.archive?.(source) ?? new PMTiles(source, directories)
  const makeCanvas = dependencies.canvas ?? (() => document.createElement('canvas'))
  const dispose = () => { lifetime.abort(); signal.removeEventListener('abort', cancel); cache.clear() }
  // Decoded parent tiles, most recent last; both providers share them.
  const cache = new Map<string, Promise<Decoded | undefined>>()
  let loading = 0
  const parallel = groundParallel(layer.url, 6)
  const parent = (x: number, y: number) => {
    const key = `${x}/${y}`, hit = cache.get(key)
    if (hit) { cache.delete(key); cache.set(key, hit); return hit }
    loading++
    // A hung range request must not hold one of the loading slots for the rest of the session.
    const made = archive.getZxy(layer.level, x, y, AbortSignal.any([lifetime.signal, AbortSignal.timeout(30000)])).then(tile => tile ? decode(tile.data) : undefined)
      .finally(() => { loading-- })
    // By identity: an evicted-then-refetched key must not lose its newer entry when the old request fails.
    made.catch(() => { if (cache.get(key) === made) cache.delete(key) })
    cache.set(key, made)
    // A level-12 request alone needs 16 archive tiles; hold a few such views.
    while (cache.size > 128) cache.delete(cache.keys().next().value!)
    return made
  }
  try {
    const header = await archive.getHeader()
    if (header.tileType !== TileType.Mvt || header.minZoom !== layer.level || header.maxZoom !== layer.level
      || [header.minLon, header.minLat, header.maxLon, header.maxLat].some((value, i) => !Number.isFinite(value) || Math.abs(value - layer.bounds[i]!) > 1e-7)) throw Error('Ground vector header differs from descriptor')
    // Warm the whole index at open (8 leaf directories, ~77 KB, merged into one read by the range source): otherwise
    // the first tile on a CDN waits root -> leaf -> tile in turn (~0.1-0.2 s on R2). Small indexes only.
    if (directories) {
      const full = header as unknown as Header
      void directories.getDirectory(source, full.rootDirectoryOffset, full.rootDirectoryLength, full).then(root => {
        const leaves = root.filter(entry => entry.runLength === 0)
        if (leaves.length <= 24) return Promise.all(leaves.map(entry => directories.getDirectory(source, full.leafDirectoryOffset + entry.offset, entry.length, full)))
      }).catch(() => {})
    }
    const transparent = makeCanvas(); transparent.width = transparent.height = TILE
    const make = (kind: 'landcover' | 'roads') => ({
      tileWidth: TILE, tileHeight: TILE, minimumLevel: 0, maximumLevel: VECTOR_MAX_LEVEL,
      tilingScheme: new C.WebMercatorTilingScheme(), rectangle: C.Rectangle.fromDegrees(...layer.bounds), hasAlphaChannel: true,
      credit: new C.Credit(layer.credit.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')), errorEvent: new C.Event(), tileDiscardPolicy: undefined,
      ready: true, readyPromise: Promise.resolve(true), proxy: undefined,
      getTileCredits: () => undefined, pickFeatures: () => undefined,
      coversPosition: (lon: number, lat: number) => Number.isFinite(lon) && Number.isFinite(lat)
        && lon >= layer.bounds[0] && lon <= layer.bounds[2] && lat >= layer.bounds[1] && lat <= layer.bounds[3],
      requestImage(x: number, y: number, level: number) {
        if (lifetime.signal.aborted) return undefined
        // Only the far horizon (coarser levels) is left to the PNG pyramid underneath; this layer is see-through there.
        if (![x, y, level].every(Number.isInteger) || level < VECTOR_MIN_LEVEL(layer.level) || level > VECTOR_MAX_LEVEL) return Promise.resolve(transparent)
        // Deeper levels crop one archive tile; the archive level and the two above it draw 1, 2x2 or 4x4 whole tiles.
        const d = Math.max(0, level - layer.level), n = 2 ** Math.max(0, layer.level - level)
        const keys: [number, number][] = []
        for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) keys.push(d ? [x >> d, y >> d] : [x * n + i, y * n + j])
        // A merged request starts all its missing parents together (up to 16 past the cap). Gating on loading+missing
        // measured slower (jump to all-vector 3.5-3.9 s vs 2.4-2.7 s): the browser queues the excess sockets itself.
        const missing = keys.some(([px, py]) => !cache.has(`${px}/${py}`))
        if (missing && loading >= parallel) return undefined
        // One failed parent (timeout, decode) is fetched once more; the rest of the merged tile still draws.
        const settled = (px: number, py: number) => parent(px, py).catch(() => parent(px, py)).catch(() => undefined)
        return Promise.all(keys.map(([px, py]) => settled(px, py))).then(tiles => {
          if (tiles.every(tile => !tile)) return transparent
          const canvas = makeCanvas(); canvas.width = canvas.height = TILE
          const context = canvas.getContext('2d'); if (!context) throw Error('Ground canvas unavailable')
          tiles.forEach((tile, k) => {
            if (!tile) return
            const shapes = kind === 'roads' ? tile.roads : tile.landcover
            const span = tile.extent / 2 ** d, sx = d ? (x - (keys[k]![0] << d)) * span : 0, sy = d ? (y - (keys[k]![1] << d)) * span : 0
            const scale = TILE / n / span, ox = (k % n) * TILE / n, oy = Math.floor(k / n) * TILE / n
            // Shapes under one output texel cannot show; merged far tiles are mostly such shapes.
            const texel = 1 / scale
            const inView = (shape: Shape) => !(shape.box[2] < sx || shape.box[0] > sx + span || shape.box[3] < sy || shape.box[1] > sy + span)
              && (shape.box[2] - shape.box[0] >= texel || shape.box[3] - shape.box[1] >= texel)
            context.setTransform(scale, 0, 0, scale, ox - sx * scale, oy - sy * scale)
            for (const shape of shapes) {
              if (!inView(shape)) continue
              context.fillStyle = kind === 'roads' ? ROAD_COLOUR : LANDCOVER_COLOURS[shape.c] ?? 'transparent'
              context.fill(shape.path)
            }
            // A one-texel kerb line reads as a drawn map, not a blurred photo; merged far tiles stay fill-only.
            if (kind === 'roads' && n === 1) {
              context.lineWidth = 1 / scale; context.strokeStyle = ROAD_EDGE
              for (const shape of shapes) if (inView(shape)) context.stroke(shape.path)
            }
          })
          return bleed(context.getImageData(0, 0, TILE, TILE).data)
        })
      },
      dispose,
    })
    return { landcover: make('landcover'), roads: make('roads'), dispose }
  } catch (error) { dispose(); throw error }
}
