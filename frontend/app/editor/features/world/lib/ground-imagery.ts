import { PMTiles, ResolvedValueCache, TileType, type Header, type Source } from 'pmtiles'

export type GroundImageryLayer = { kind: 'landcover' | 'roads'; url: string; sha256: string;
  bounds: [number, number, number, number]; minLevel: number; maxLevel: number; credit: string }
type Archive = { getHeader(): Promise<Header>; getZxy(z: number, x: number, y: number, signal?: AbortSignal): Promise<{ data: ArrayBuffer } | undefined> }
type Fetch = (url: string, init?: RequestInit) => Promise<Response>
type Bitmap = { width: number; height: number; close(): void }
type Canvas = { width: number; height: number; getContext(kind: '2d'): { drawImage(image: any, x: number, y: number): void } | null }
type Dependencies = { get?: Fetch; archive?: (source: Source) => Archive; decode?: (data: ArrayBuffer) => Promise<Bitmap>; canvas?: () => Canvas }
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).sort().join(',') === [...keys].sort().join(',')
const abortError = () => new DOMException('Ground imagery cancelled', 'AbortError')
const safeUrl = (value: unknown, archive = false): value is string => {
  if (typeof value !== 'string' || !/^(https?:\/\/|\/[^/])/.test(value) || value.includes('\\')) return false
  const url = new URL(value, 'https://local.invalid')
  return !url.username && !url.password && !url.hash && !url.search && (!archive || url.pathname.endsWith('.pmtiles'))
}

export function validateGroundImagery(value: unknown): GroundImageryLayer[] {
  const descriptor = value as { schema?: string; layers?: unknown[] } | null
  if (!descriptor || !exactKeys(descriptor, ['schema', 'layers']) || descriptor.schema !== 'world-ground/imagery-v1'
    || !Array.isArray(descriptor.layers) || descriptor.layers.length < 1 || descriptor.layers.length > 2) throw Error('Invalid ground imagery descriptor')
  const kinds = new Set<string>()
  const layers = descriptor.layers.map(item => {
    const layer = item as GroundImageryLayer
    if (!layer || !exactKeys(layer, ['kind', 'url', 'sha256', 'bounds', 'minLevel', 'maxLevel', 'credit'])
      || !['landcover', 'roads'].includes(layer.kind) || kinds.has(layer.kind) || !safeUrl(layer.url, true)
      || !/^[a-f0-9]{64}$/.test(layer.sha256) || !Array.isArray(layer.bounds) || layer.bounds.length !== 4 || !layer.bounds.every(Number.isFinite)
      || layer.bounds[0] < -180 || layer.bounds[2] > 180 || layer.bounds[1] < -85.05112878 || layer.bounds[3] > 85.05112878
      || layer.bounds[0] >= layer.bounds[2] || layer.bounds[1] >= layer.bounds[3]
      || !Number.isInteger(layer.minLevel) || !Number.isInteger(layer.maxLevel) || layer.minLevel < 0 || layer.maxLevel > 12 || layer.minLevel > layer.maxLevel
      || typeof layer.credit !== 'string' || !layer.credit.trim() || layer.credit.length > 500) throw Error('Invalid ground imagery layer')
    kinds.add(layer.kind); return structuredClone(layer)
  })
  return layers.sort((a, b) => Number(a.kind === 'roads') - Number(b.kind === 'roads'))
}

async function boundedBody(response: Response, limit: number): Promise<ArrayBuffer> {
  const declared = response.headers.get('Content-Length')
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > limit)) { await response.body?.cancel(); throw Error('Ground imagery response too large') }
  if (!response.body) throw Error('Missing ground imagery body')
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let length = 0
  try {
    for (;;) {
      const result = await reader.read(); if (result.done) break
      length += result.value.length
      if (length > limit) throw Error('Ground imagery response too large')
      chunks.push(result.value)
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error }
  finally { reader.releaseLock() }
  const result = new Uint8Array(length); let offset = 0
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length }
  return result.buffer
}

export function groundRangeSource(layer: GroundImageryLayer, lifetime: AbortSignal, get: Fetch = (url, init) => fetch(url, init)): Source {
  let etag: string | undefined
  return { getKey: () => `${layer.url}#${layer.sha256}`,
    async getBytes(offset, length, signal) {
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(length) || offset < 0 || length < 1 || length > 4 * 1024 ** 2) throw Error('Invalid ground archive range')
      const combined = signal ? AbortSignal.any([lifetime, signal]) : lifetime
      combined.throwIfAborted()
      const response = await get(layer.url, { headers: { Range: `bytes=${offset}-${offset + length - 1}` }, signal: combined })
      if (response.status !== 206) { await response.body?.cancel(); throw Error(`Ground archive requires HTTP 206, got ${response.status}`) }
      const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('Content-Range') ?? '')
      if (!range || !range.slice(1).every(value => Number.isSafeInteger(Number(value))) || Number(range[3]) <= offset
        || Number(range[1]) !== offset || Number(range[2]) !== Math.min(offset + length, Number(range[3])) - 1) {
        await response.body?.cancel(); throw Error('Ground archive Content-Range mismatch')
      }
      const current = response.headers.get('ETag') ?? undefined
      if (etag !== undefined && current !== etag) { await response.body?.cancel(); throw Error('Ground archive changed ETag') }
      etag ??= current
      const data = await boundedBody(response, length)
      combined.throwIfAborted()
      if (data.byteLength !== Number(range[2]) - offset + 1) throw Error('Truncated ground archive range')
      return { data, etag: current }
    },
  }
}

function raced<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError())
  return new Promise((resolve, reject) => {
    const cancelled = () => { signal.removeEventListener('abort', cancelled); reject(abortError()) }
    signal.addEventListener('abort', cancelled, { once: true })
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', cancelled))
  })
}

/** Canvas ownership passes to Cesium; decoded bitmaps are closed before returning, never retained in an eviction cache. */
export async function createGroundImageryProvider(C: any, layer: GroundImageryLayer, signal: AbortSignal, dependencies: Dependencies = {}) {
  const lifetime = new AbortController(), cancel = () => lifetime.abort()
  signal.addEventListener('abort', cancel, { once: true }); if (signal.aborted) cancel()
  const source = groundRangeSource(layer, lifetime.signal, dependencies.get)
  const archive = dependencies.archive?.(source) ?? new PMTiles(source, new ResolvedValueCache(32))
  const makeCanvas = dependencies.canvas ?? (() => document.createElement('canvas'))
  const decode = dependencies.decode ?? (data => createImageBitmap(new Blob([data], { type: 'image/png' })))
  const jobs = new Set<AbortController>()
  const dispose = () => { lifetime.abort(); signal.removeEventListener('abort', cancel); for (const job of jobs) job.abort() }
  try {
    const header = await raced(archive.getHeader(), lifetime.signal)
    if (header.tileType !== TileType.Png || header.minZoom !== layer.minLevel || header.maxZoom !== layer.maxLevel
      || [header.minLon, header.minLat, header.maxLon, header.maxLat].some((value, i) => !Number.isFinite(value) || Math.abs(value - layer.bounds[i]!) > 1e-7)) throw Error('Ground archive header differs from descriptor')
    const transparent = makeCanvas(); transparent.width = transparent.height = 256
    const rectangle = C.Rectangle.fromDegrees(...layer.bounds)
    const provider = {
      tileWidth: 256, tileHeight: 256, minimumLevel: layer.minLevel, maximumLevel: layer.maxLevel,
      tilingScheme: new C.WebMercatorTilingScheme(), rectangle, hasAlphaChannel: true,
      credit: new C.Credit(layer.credit.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')), errorEvent: new C.Event(), tileDiscardPolicy: undefined,
      ready: true, readyPromise: Promise.resolve(true), proxy: undefined,
      getTileCredits: () => undefined, pickFeatures: () => undefined,
      requestImage(x: number, y: number, level: number, request?: { cancelled?: boolean; cancelFunction?: () => void }) {
        if (lifetime.signal.aborted || request?.cancelled || jobs.size >= 4) return undefined
        if (![x, y, level].every(Number.isInteger) || level < layer.minLevel || level > layer.maxLevel || x < 0 || y < 0 || x >= 2 ** level || y >= 2 ** level) return Promise.resolve(transparent)
        const width = 360 / 2 ** level, west = x * width - 180
        const latitude = (row: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * row / 2 ** level))) * 180 / Math.PI
        if (west >= layer.bounds[2] || west + width <= layer.bounds[0] || latitude(y) <= layer.bounds[1] || latitude(y + 1) >= layer.bounds[3]) return Promise.resolve(transparent)
        const job = new AbortController(); jobs.add(job)
        const combined = AbortSignal.any([lifetime.signal, job.signal]); if (request) request.cancelFunction = () => job.abort()
        const task = (async () => {
          const tile = await archive.getZxy(level, x, y, combined); combined.throwIfAborted()
          if (!tile) return transparent
          const data = new DataView(tile.data)
          if (tile.data.byteLength > 1024 ** 2 || tile.data.byteLength < 29 || data.getUint32(0) !== 0x89504e47 || data.getUint32(4) !== 0x0d0a1a0a
            || data.getUint32(8) !== 13 || data.getUint32(12) !== 0x49484452
            || data.getUint32(16) !== 256 || data.getUint32(20) !== 256 || data.getUint8(24) !== 8 || data.getUint8(25) !== 6) throw Error('Expected 256px RGBA PNG ground tile')
          const bitmap = await decode(tile.data)
          try {
            combined.throwIfAborted()
            if (bitmap.width !== 256 || bitmap.height !== 256) throw Error('Ground bitmap dimensions mismatch')
            const canvas = makeCanvas(); canvas.width = canvas.height = 256
            const context = canvas.getContext('2d'); if (!context) throw Error('Ground canvas unavailable')
            context.drawImage(bitmap, 0, 0); return canvas
          } finally { bitmap.close() }
        })().finally(() => jobs.delete(job))
        return raced(task, combined)
      },
      dispose,
    }
    return provider
  } catch (error) { dispose(); throw error }
}

export async function prepareGroundImagery(C: any, options: Dependencies & { signal?: AbortSignal; descriptorUrl?: string } = {}) {
  const controller = new AbortController(), cancel = () => controller.abort()
  options.signal?.addEventListener('abort', cancel, { once: true }); if (options.signal?.aborted) cancel()
  const layers: { kind: GroundImageryLayer['kind']; provider: Awaited<ReturnType<typeof createGroundImageryProvider>> }[] = []
  const dispose = () => { controller.abort(); options.signal?.removeEventListener('abort', cancel); for (const layer of layers) layer.provider.dispose() }
  try {
    const base = process.env.NEXT_PUBLIC_WORLD_GROUND_BASE_URL
    const url = options.descriptorUrl ?? (base ? `${base.replace(/\/+$/, '')}/latest.json` : `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/map-data/world-ground/latest.json`)
    if (!safeUrl(url)) throw Error('Invalid ground imagery descriptor URL')
    const response = await (options.get ?? fetch)(url, { signal: controller.signal })
    controller.signal.throwIfAborted()
    if (response.status !== 404) {
      if (!response.ok) throw Error(`Ground imagery descriptor ${response.status}`)
      const descriptor = validateGroundImagery(JSON.parse(new TextDecoder().decode(await boundedBody(response, 32 * 1024))))
      for (const layer of descriptor) layers.push({ kind: layer.kind, provider: await createGroundImageryProvider(C, layer, controller.signal, options) })
    }
    controller.signal.throwIfAborted()
    return { layers, dispose }
  } catch (error) { dispose(); throw error }
}
