import { join } from 'node:path'
import { preparedMapAsset } from '@/lib/map-data-roots'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

async function handle(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return preparedMapAsset((await params).path, join(process.cwd(), 'public'), request.method === 'HEAD', request.signal, request.headers.get('range') ?? undefined)
}

export { handle as GET, handle as HEAD }
