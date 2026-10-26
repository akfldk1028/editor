import { backendRequest } from '@/lib/backend-request'

export async function GET(request: Request, { params }: { params: Promise<{ tile: string[] }> }) {
  const path = (await params).tile.join('/')
  const match = /^(?:[a-f0-9]{64}\/)?(1[3-7])\/(\d{1,6})\/(\d{1,6})\.png$/.exec(path)
  if (!match || Number(match[2]) >= 2 ** Number(match[1]) || Number(match[3]) >= 2 ** Number(match[1])) {
    return Response.json({ detail: 'Invalid road imagery tile' }, { status: 400 })
  }
  return backendRequest(request, `/api/v1/land/road-imagery/${path}`)
}
