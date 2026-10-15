import { backendRequest } from '@/lib/backend-request';
import { isPlatformDesignOperation } from '@/lib/platform-design-operation';

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  const id = '[A-Za-z0-9_-]{1,200}';
  if (!/^projects\/[A-Za-z0-9_-]{1,200}\/conversation$/.test(route) && !isPlatformDesignOperation('GET', route) && !new RegExp(`^(agents|agents/${id}/tasks|agents/${id}/tasks/${id}|ledger/hops|ledger/hops/stream|ledger/hops/[0-9]{1,12}|status|capabilities|projects|projects/${id}|projects/${id}/(runs|runs/latest|context|design/selection/mass)|runs/${id}(/request|/results)?|scene-assets/[a-f0-9]{64}\\.glb|host/status)$`).test(route)) {
    return Response.json({ detail: 'Unknown platform operation' }, { status: 404 });
  }
  return backendRequest(request, `/api/v1/platform/${route}`, { stream: route === 'ledger/hops/stream' });
}

export async function POST(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!/^projects\/[A-Za-z0-9_-]{1,200}\/conversation$/.test(route) && !isPlatformDesignOperation('POST', route) && !/^(ask|law-analysis|ordinances|ordinances\/body|host\/(ensure|touch)|projects|projects\/[A-Za-z0-9_-]{1,200}\/(runs|scene-revision|conversations|runs\/[A-Za-z0-9_.:-]{1,200}\/resume))$/.test(route)) {
    return Response.json({ detail: 'Unknown platform operation' }, { status: 404 });
  }
  // A law analysis asks the Law Agent for the whole parcel (42 regulations, lines, caps): a minute is not enough on a cold agent.
  return backendRequest(request, `/api/v1/platform/${route}`, route === 'law-analysis' || route === 'ask' ? { timeoutMs: 240_000 } : {});
}
