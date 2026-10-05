import { backendRequest } from '@/lib/backend-request'
import { isDesignOperation } from '@/lib/design-operation-path'

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join('/').replace(/\/$/, '')
  if (!isDesignOperation(request.method, path)) {
    return Response.json({ error: 'Unknown design operation' }, { status: 404 })
  }
  const encodedPath = path.split('/').map(encodeURIComponent).join('/')
  return backendRequest(request, `/api/v1/design/${encodedPath}`, { stream: path.endsWith('/stream') })
}
export const GET = handle
export const POST = handle
