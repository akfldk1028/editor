import { backendRequest } from '@/lib/backend-request'

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join('/')
  const allowed = {
    GET: /^(settings|health|version|teams(?:\/\d+)?|galleries(?:\/\d+)?|sessions(?:\/\d+\/runs)?|runs\/capabilities|runs\/[a-f0-9]{32}\/events)$/,
    POST: /^(teams|galleries|sessions|runs(?:\/[a-f0-9]{32}\/(start|input|stop))?|mcp\/connections(?:\/[a-f0-9]{32}\/operations)?|validate(?:\/test)?)$/,
    PUT: /^(settings|teams\/\d+|galleries\/\d+)$/,
    DELETE: /^(teams\/\d+|galleries\/\d+|sessions\/\d+|mcp\/connections\/[a-f0-9]{32})$/,
  }[request.method]
  if (!allowed?.test(path)) return Response.json({ detail: 'Unknown workspace operation' }, { status: 404 })
  return backendRequest(request, `/api/v1/workspace/${path}`)
}

export const GET = handle
export const PUT = handle
export const POST = handle
export const DELETE = handle
