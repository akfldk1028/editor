const apiRoot = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1`;
import type { LawSearchRequest, LawSearchResponse, DomainInfo, ArticleDetail } from './types';

function transformResponse(data: LawSearchResponse, query: string): LawSearchResponse {
  return {
    ...data,
    total_count: data.total_count ?? data.results.length,
    query: data.query ?? query,
  };
}

export async function search(req: LawSearchRequest): Promise<LawSearchResponse> {
  const res = await fetch(`${apiRoot}/law/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ q: req.query, limit: req.limit }),
  });
  if (!res.ok) throw new Error(`Search failed: ${res.status}`);
  const data = await res.json();
  return transformResponse(data, req.query);
}

export async function searchInDomain(domainId: string, req: LawSearchRequest): Promise<LawSearchResponse> {
  const res = await fetch(`${apiRoot}/law/domain/${encodeURIComponent(domainId)}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ q: req.query, limit: req.limit }),
  });
  if (!res.ok) throw new Error(`Domain search failed: ${res.status}`);
  const data = await res.json();
  return transformResponse(data, req.query);
}

export async function getDomains(): Promise<DomainInfo[]> {
  const res = await fetch(`${apiRoot}/law/domains`);
  if (!res.ok) throw new Error(`Get domains failed: ${res.status}`);
  const data = await res.json();
  return data.domains ?? [];
}

export async function healthCheck(): Promise<void> {
  const res = await fetch(`${apiRoot}/law/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
}

export async function getArticle(fullId: string): Promise<ArticleDetail> {
  const res = await fetch(`${apiRoot}/law/article?full_id=${encodeURIComponent(fullId)}`);
  if (!res.ok) throw new Error(`Get article failed: ${res.status}`);
  return res.json();
}
