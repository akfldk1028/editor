import { backendRequest } from '@/lib/backend-request'

export async function GET(request: Request, { params }: { params: Promise<{ tile: string[] }> }) {
  const path = (await params).tile.join('/')
  if (!/^\d{1,2}\/\d{1,6}\/\d{1,6}\.png$/.test(path)) {
    return Response.json({ detail: 'Invalid tile path' }, { status: 400 })
  }
  return backendRequest(request, `/api/v1/land/tiles/${path}`)
}
