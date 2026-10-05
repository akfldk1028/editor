import { backendRequest } from '@/lib/backend-request';
import { isPlatformDesignOperation } from '@/lib/platform-design-operation';

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  const id = '[A-Za-z0-9_-]{1,200}';
  if (!isPlatformDesignOperation('GET', route) && !new RegExp(`^(agents|projects|projects/${id}|projects/${id}/(runs|context|design/selection/mass)|runs/${id}|scene-assets/[a-f0-9]{64}\\.glb)$`).test(route)) {
    return Response.json({ detail: 'Unknown platform operation' }, { status: 404 });
  }
  return backendRequest(request, `/api/v1/platform/${route}`);
}

export async function POST(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!isPlatformDesignOperation('POST', route) && !/^(projects|projects\/[A-Za-z0-9_-]{1,200}\/runs)$/.test(route)) {
    return Response.json({ detail: 'Unknown platform operation' }, { status: 404 });
  }
  return backendRequest(request, `/api/v1/platform/${route}`);
}
