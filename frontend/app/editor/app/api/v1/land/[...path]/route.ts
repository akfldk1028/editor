import { backendRequest } from '@/lib/backend-request'

// One entry per backend land operation the browser may reach; tiles/ has its own route.
const methods: Record<string, string> = {
  zones: 'GET', stats: 'GET', analyze: 'POST', resolve: 'POST', reverse: 'POST', 'parcel-geometry': 'POST',
  wms: 'GET', 'map-config': 'GET', 'agent-analyze/stream': 'GET',
}

async function handle(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const operation = (await params).path.join('/')
  if (!methods[operation]) return Response.json({ detail: 'Unknown land operation' }, { status: 404 })
  if (methods[operation] !== request.method) return Response.json({ detail: 'Method not allowed' }, { status: 405 })
  return backendRequest(request, `/api/v1/land/${operation}`, { stream: operation.endsWith('/stream') })
}

export { handle as GET, handle as POST }
