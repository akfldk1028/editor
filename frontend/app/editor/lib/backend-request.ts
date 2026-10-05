export async function backendRequest(request: Request, path: string, options: { stream?: boolean } = {}) {
  const origin = request.headers.get('origin')
  const publicUrl = new URL(request.url)
  // Next can reconstruct request.url with its internal hostname. Host retains
  // the browser-facing authority; the backend also checks its configured origin.
  if (request.headers.get('host')) publicUrl.host = request.headers.get('host')!
  if (request.method !== 'GET' && (request.headers.get('sec-fetch-site') === 'cross-site' || (origin && origin !== publicUrl.origin))) {
    return Response.json({ detail: 'Cross-origin changes are not allowed' }, { status: 403 })
  }
  const backend = process.env.EDITOR_BACKEND_URL
  if (!backend) return Response.json({ detail: 'Editor backend is not configured' }, { status: 503 })
  let destination: URL
  try {
    const configured = new URL(backend)
    if (!['http:', 'https:'].includes(configured.protocol)) throw new Error('Unsupported backend protocol')
    destination = new URL(path, configured)
  } catch {
    return Response.json({ detail: 'Editor backend configuration is invalid' }, { status: 503 })
  }
  destination.search = new URL(request.url).search
  try {
    const upstream = await fetch(destination, {
      method: request.method,
      headers: { 'Content-Type': 'application/json', ...(origin ? { Origin: origin } : {}),
        ...(request.headers.has('last-event-id') ? { 'Last-Event-ID': request.headers.get('last-event-id')! } : {}),
        ...(request.headers.has('idempotency-key') ? { 'Idempotency-Key': request.headers.get('idempotency-key')! } : {}) },
      body: request.method === 'GET' ? undefined : await request.text(),
      cache: 'no-store', signal: options.stream ? request.signal : AbortSignal.any([request.signal, AbortSignal.timeout(60_000)]), redirect: 'error',
    })
    return new Response(upstream.body, { status: upstream.status, headers: {
      'Content-Type': upstream.headers.get('content-type') || 'application/json',
      'Cache-Control': upstream.headers.get('cache-control') || 'no-store',
      'X-Content-Type-Options': 'nosniff',
    } })
  } catch {
    return Response.json({ detail: 'Editor backend is unavailable' }, { status: 502 })
  }
}
