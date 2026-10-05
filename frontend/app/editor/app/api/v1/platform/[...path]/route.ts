import { backendRequest } from '@/lib/backend-request';

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  const id = '[A-Za-z0-9_-]{1,200}';
  if (!new RegExp(`^(agents|projects|projects/${id}|projects/${id}/(runs|context)|runs/${id})$`).test(route)) {
    return Response.json({ detail: 'Unknown platform operation' }, { status: 404 });
  }
  return backendRequest(request, `/api/v1/platform/${route}`);
}

export async function POST(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!/^(projects|projects\/[A-Za-z0-9_-]{1,200}\/runs)$/.test(route)) {
    return Response.json({ detail: 'Unknown platform operation' }, { status: 404 });
  }
  return backendRequest(request, `/api/v1/platform/${route}`);
}
