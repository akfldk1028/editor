const methods: Record<string, string> = { zones: 'GET', stats: 'GET', analyze: 'POST', resolve: 'POST' }

async function handle(request: Request, { params }: { params: Promise<{ operation: string }> }) {
  const { operation } = await params
  if (!methods[operation]) return Response.json({ detail: 'Unknown land operation' }, { status: 404 })
  if (methods[operation] !== request.method) return Response.json({ detail: 'Method not allowed' }, { status: 405 })
  const origin = request.headers.get('origin')
  if (request.method === 'POST' && (request.headers.get('sec-fetch-site') === 'cross-site' || (origin && origin !== new URL(request.url).origin))) {
    return Response.json({ detail: 'Cross-origin analysis is not allowed' }, { status: 403 })
  }
  const backend = process.env.EDITOR_BACKEND_URL
  if (!backend) return Response.json({ detail: 'Editor backend is not configured' }, { status: 503 })
  try {
    const upstream = await fetch(new URL(`/api/v1/land/${operation}`, backend), {
      method: request.method,
      headers: { 'Content-Type': 'application/json', ...(origin ? { Origin: origin } : {}) },
      body: request.method === 'POST' ? await request.text() : undefined,
      cache: 'no-store', signal: AbortSignal.timeout(60_000), redirect: 'error',
    })
    return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store' } })
  } catch {
    return Response.json({ detail: 'Editor backend is unavailable' }, { status: 502 })
  }
}

export { handle as GET, handle as POST }
