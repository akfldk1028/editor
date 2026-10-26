import { open } from 'node:fs/promises'
import { join } from 'node:path'
import { Readable } from 'node:stream'

const roots = new Set(['world-ground', 'world-terrain', 'world-buildings', 'buildings', 'releases'])
const types: Record<string, string> = { pmtiles: 'application/octet-stream', json: 'application/json', b3dm: 'application/octet-stream',
  glb: 'model/gltf-binary', gltf: 'model/gltf+json', bin: 'application/octet-stream', png: 'image/png', jpg: 'image/jpeg' }

/** Next's production public-file index cannot discover assets published after startup. */
export async function preparedMapFile(parts: string[], publicRoot: string, head = false, signal?: AbortSignal, range?: string, assetRoot?: string): Promise<Response> {
  const name = parts.at(-1) ?? '', extension = name.split('.').at(-1) ?? ''
  const gzip = name.endsWith('.b3dm.gz')
  const contentType = types[gzip ? 'b3dm' : extension]
  if (parts[0] === 'releases' && !(parts.length === 2 && name === 'current.json')
    && !(parts.length === 3 && /^[a-f0-9]{64}$/.test(parts[1]!) && name === 'manifest.json')) return new Response(null, { status:404 })
  if (name === 'upload-plan.json' || parts.length < 2 || !roots.has(parts[0]!) || !contentType
    || parts.some(p => !/^[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*$/.test(p))) return new Response(null, { status: 404 })
  let file: Awaited<ReturnType<typeof open>> | undefined
  try {
    file = await open(assetRoot ? join(assetRoot, ...parts.slice(1)) : join(publicRoot, ...parts), 'r')
    // Stat the opened handle so an atomic publication cannot mismatch length/body.
    const stat = await file.stat()
    if (!stat.isFile()) { await file.close(); return new Response(null, { status: 404 }) }
    // A partial gzip representation cannot be decoded independently. Ignore Range
    // for these whole-tile assets; PMTiles and uncompressed files retain ranges.
    if (gzip) range = undefined
    let start = 0, end = stat.size - 1
    if (range) {
      const match = /^bytes=(\d*)-(\d*)$/.exec(range)
      if (match && (match[1] || match[2])) {
        start = match[1] ? Number(match[1]) : Math.max(0, stat.size - Number(match[2]))
        end = match[1] && match[2] ? Math.min(end, Number(match[2])) : end
      } else start = -1
      if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start > end || start >= stat.size) {
        await file.close()
        return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${stat.size}` } })
      }
    }
    const status = range ? 206 : 200
    const headers: Record<string, string> = { 'Content-Type': contentType!, 'Content-Length': String(Math.max(0, end - start + 1)),
      'Accept-Ranges': gzip ? 'none' : 'bytes', 'ETag': `"${stat.size.toString(16)}-${Math.trunc(stat.mtimeMs).toString(16)}"`,
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': /^[a-f0-9]{64}\.json$/.test(name) || /^terrain-[a-f0-9]{20}\.pmtiles$/.test(name) || parts.slice(1,-1).some(p => /^(?:[a-f0-9]{64}|\d{8}-[a-f0-9]{8})$/.test(p)) ? 'public, max-age=31536000, immutable'
        : name === 'current.json' ? 'no-store' : name === 'latest.json' ? 'public, max-age=60'
        : name === 'archive.json' || name === 'catalog.json' || name === 'local-source.json' ? 'no-store' : 'public, max-age=3600' }
    if (gzip) headers['Content-Encoding'] = 'gzip'
    if (range) headers['Content-Range'] = `bytes ${start}-${end}/${stat.size}`
    if (head) { await file.close(); return new Response(null, { headers, status }) }
    const handle = file, source = handle.createReadStream({ autoClose: false, ...(range ? { start, end } : {}) })
    let closing = false
    const abort = () => { source.destroy() }
    const close = () => {
      if (closing) return
      closing = true
      signal?.removeEventListener('abort', abort)
      void handle.close().catch(() => {})
    }
    source.once('end', close)
    source.once('close', close)
    source.once('error', close)
    signal?.addEventListener('abort', abort, { once: true })
    const stream = Readable.toWeb(source) as unknown as ReadableStream<Uint8Array>
    if (signal?.aborted) abort()
    return new Response(stream, { headers, status })
  } catch (error) {
    await file?.close().catch(() => {})
    const code = (error as NodeJS.ErrnoException).code
    return new Response(null, { status: code === 'ENOENT' || code === 'ENOTDIR' ? 404 : 503 })
  }
}
