// Cloudflare Worker `map-range-cache`, routed on map.latentarchitecture.app/world-ground/* and /world-terrain/*.
// The PMTiles archives (1.8-15 GB) exceed the free plan's 512 MB cacheable object size, so Cloudflare bypasses its
// cache for their range requests. This Worker caches each requested byte range as its own small edge object.
// Archive paths are content-addressed, so a cached range never goes stale.
const ORIGINS = new Set([
  'http://127.0.0.1:3003', 'http://localhost:3003', 'http://127.0.0.1:3005', 'http://localhost:3005',
  'https://latentarchitecture.app', 'https://www.latentarchitecture.app',
])

function cors(headers, origin) {
  if (ORIGINS.has(origin)) {
    headers.set('Access-Control-Allow-Origin', origin)
    headers.set('Access-Control-Expose-Headers', 'Content-Range,ETag,Content-Length,Accept-Ranges,X-Range-Cache')
    headers.append('Vary', 'Origin')
  }
  return headers
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url), range = request.headers.get('Range'), origin = request.headers.get('Origin')
    if (request.method !== 'GET' || !range || !url.pathname.endsWith('.pmtiles')) return fetch(request)
    const key = new Request(`${url.origin}${url.pathname}?range=${encodeURIComponent(range)}`)
    let state = 'hit', hit = await caches.default.match(key)
    if (!hit) {
      state = 'miss'
      const upstream = await fetch(url.toString(), { headers: { Range: range } })
      if (upstream.status !== 206) return upstream
      // The Cache API refuses 206 responses: store the bytes as a 200 under a range-specific key.
      hit = new Response(await upstream.arrayBuffer(), { headers: {
        'Content-Type': upstream.headers.get('Content-Type') || 'application/octet-stream',
        'X-Range': upstream.headers.get('Content-Range') || '', 'ETag': upstream.headers.get('ETag') || '',
        'Cache-Control': 'public, max-age=31536000, immutable',
      } })
      ctx.waitUntil(caches.default.put(key, hit.clone()))
    }
    const headers = new Headers(hit.headers)
    headers.set('Content-Range', headers.get('X-Range')); headers.delete('X-Range')
    headers.set('Accept-Ranges', 'bytes'); headers.set('X-Range-Cache', state)
    return new Response(hit.body, { status: 206, headers: cors(headers, origin) })
  },
}
