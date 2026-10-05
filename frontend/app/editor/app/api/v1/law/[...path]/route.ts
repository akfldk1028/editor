import { backendRequest } from '@/lib/backend-request'

async function handle(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  const joined = path.join('/')
  const method = ['health', 'domains', 'article', 'search/stream'].includes(joined) ? 'GET'
    : joined === 'search' || /^domain\/[a-zA-Z0-9_-]+\/search$/.test(joined) ? 'POST' : null
  if (!method) return Response.json({ detail: 'Unknown law operation' }, { status: 404 })
  if (request.method !== method) return Response.json({ detail: 'Method not allowed' }, { status: 405 })
  return backendRequest(request, `/api/v1/law/${joined}`)
}

export { handle as GET, handle as POST }
