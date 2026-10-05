import { backendRequest } from '@/lib/backend-request'

const readPaths = /^(?:maas\/(?:language-system|outcome-graph|executed-masses(?:\/\d+(?:\/passport)?)?|geometry-shapes\/\d+(?:\/passport)?|creative-portfolios|portfolio-evaluations)|jobs\/[a-f0-9]{32}(?:\/(?:results(?:\/\d+\/evidence)?|stream))?|collaboration\/(?:health|bus\/log|transcript))$/
const writePaths = /^(?:site-boundary|auto-constraints|floor-plan|constraints\/visualize|jobs(?:\/[a-f0-9]{32}\/(?:run|cancel|results\/\d+\/aesthetic))?|interactive\/(?:patch|preview|operation)|maas\/(?:legal-variants|single-executions(?:\/[A-Za-z0-9_-]+\/vlm-review)?)|collaboration\/bus\/send)$/

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join('/').replace(/\/$/, '')
  if (!(request.method === 'GET' ? readPaths : writePaths).test(path)) {
    return Response.json({ error: 'Unknown design operation' }, { status: 404 })
  }
  return backendRequest(request, `/api/v1/design/${path}`)
}
export const GET = handle
export const POST = handle
