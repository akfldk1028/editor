async function handle(request: Request, context: { params: Promise<{ cad: string[] }> }) {
  const path = (await context.params).cad.join('/')
  const read = /^(drawing|drawings\/sessions|providers|skills|export\/capabilities|export\/reports\/[A-Za-z0-9_-]+)$/
  const write = /^(drawings\/(open|register|sessions\/[A-Za-z0-9_-]+\/activate)|chat|inspections|edit\/(preview|apply|undo|redo)|export\/(destination-grants|reports|drawings))$/
  if (!(request.method === 'GET' ? read : write).test(path)) return Response.json({ error: { message: 'Unknown CAD operation' } }, { status: 404 })
  const publicUrl = new URL(request.url)
  if (request.headers.get('host')) publicUrl.host = request.headers.get('host')!
  const origin = request.headers.get('origin')
  if (request.method !== 'GET' && (request.headers.get('sec-fetch-site') === 'cross-site' || (origin && origin !== publicUrl.origin)))
    return Response.json({ error: { message: 'Cross-origin changes are not allowed' } }, { status: 403 })
  const configured = process.env.EDITOR_DWG_BACKEND_URL
  if (!configured) return Response.json({ error: { message: 'Editor CAD service is not configured' } }, { status: 503 })
  try {
    const destination = new URL(`/api/${path}`, configured)
    if (!['http:', 'https:'].includes(destination.protocol)) throw new Error('Invalid CAD URL')
    destination.search = new URL(request.url).search
    const upstream = await fetch(destination, { method: request.method, headers: { 'Content-Type': 'application/json' },
      body: request.method === 'GET' ? undefined : await request.text(), cache: 'no-store', redirect: 'error',
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(60_000)]) })
    return new Response(upstream.body, { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store',
      ...(upstream.headers.get('content-disposition') ? { 'Content-Disposition': upstream.headers.get('content-disposition')! } : {}) } })
  } catch { return Response.json({ error: { message: 'Editor CAD service is unavailable' } }, { status: 502 }) }
}
export const GET = handle
export const POST = handle
