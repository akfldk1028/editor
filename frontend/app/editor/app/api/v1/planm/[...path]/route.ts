import { backendRequest } from '@/lib/backend-request'

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join('/')
  const id = '[A-Za-z0-9_-]+'
  const read = new RegExp(`^runs/${id}(/alternatives(/${id}/preview)?|/artifacts/[A-Za-z0-9_./-]+)?$`)
  const write = new RegExp(`^runs(/${id}/(execute|approval|dwg/(handoff|inspection)|pascal))?$`)
  if (path.split('/').some(part => part === '..' || part === '.') || !(request.method === 'GET' ? read : write).test(path))
    return Response.json({ detail: 'Unknown PLANM operation' }, { status: 404 })
  return backendRequest(request, `/api/v1/planm/${path}`)
}
export const GET = handle
export const POST = handle
