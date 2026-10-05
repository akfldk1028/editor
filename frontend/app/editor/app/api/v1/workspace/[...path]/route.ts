import { backendRequest } from '@/lib/backend-request'

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join('/')
  const allowed = {
    GET: /^(settings|health|version|teams(?:\/\d+)?|galleries(?:\/\d+)?)$/,
    POST: /^(teams|galleries|validate(?:\/test)?)$/,
    PUT: /^(settings|teams\/\d+|galleries\/\d+)$/,
    DELETE: /^(teams\/\d+|galleries\/\d+)$/,
  }[request.method]
  if (!allowed?.test(path)) return Response.json({ detail: 'Unknown workspace operation' }, { status: 404 })
  return backendRequest(request, `/api/v1/workspace/${path}`)
}

export const GET = handle
export const PUT = handle
export const POST = handle
export const DELETE = handle
