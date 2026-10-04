export type ProductRoute =
  | { kind: 'dwg' | 'planm' | 'editor' | 'agents' | 'projects' }
  | { kind: 'project'; projectId: string }
  | { kind: 'run'; runId: string };

export function resolveProductRoute(pathname: string): ProductRoute {
  const parts = pathname.replace(/\/$/, '').split('/').slice(1);
  const [surface, rawId] = parts;
  if (surface === 'editor') return { kind: 'editor' };
  if (parts.length === 1 && ['dwg', 'planm', 'agents', 'projects'].includes(surface)) {
    return { kind: surface as 'dwg' | 'planm' | 'agents' | 'projects' };
  }
  if (parts.length === 2 && rawId) {
    try {
      const id = decodeURIComponent(rawId);
      if (!/^[A-Za-z0-9_-]+$/.test(id)) return { kind: 'dwg' };
      if (surface === 'projects') return { kind: 'project', projectId: id };
      if (surface === 'runs') return { kind: 'run', runId: id };
    } catch { /* Malformed URLs use the existing default surface. */ }
  }
  return { kind: 'dwg' };
}
