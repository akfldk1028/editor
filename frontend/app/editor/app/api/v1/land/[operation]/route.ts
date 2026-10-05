import { backendRequest } from '@/lib/backend-request'

const methods: Record<string, string> = { zones: 'GET', stats: 'GET', analyze: 'POST', resolve: 'POST', reverse: 'POST', 'parcel-geometry': 'POST', wms: 'GET' }

async function handle(request: Request, { params }: { params: Promise<{ operation: string }> }) {
  const { operation } = await params
  if (!methods[operation]) return Response.json({ detail: 'Unknown land operation' }, { status: 404 })
  if (methods[operation] !== request.method) return Response.json({ detail: 'Method not allowed' }, { status: 405 })
  return backendRequest(request, `/api/v1/land/${operation}`)
}

export { handle as GET, handle as POST }
