import { productPath } from '../../../app/product-path';
export interface SavedExecution {
  catalog_id: string;
  source_namespace: string;
  snapshot_sha256: string;
  execution_id?: string | null;
  execution_state: 'archived';
  source_status?: string | null;
  metadata_status?: 'available' | 'missing' | 'metadata_unavailable';
  has_preview: boolean;
  has_passport: boolean;
  geometry_ready?: boolean;
  replay_reference?: {source_run_id: string; status: 'unresolved'};
}

export interface ExecutionArtifact {
  artifact_id: string;
  role: string;
  media_type: 'image/png' | 'application/json';
  size: number;
  sha256: string;
  inline: boolean;
}

export interface ExecutionPage<T> {items: T[]; limit?: number; offset?: number}
export interface ExecutionDetail extends ExecutionPage<ExecutionArtifact> {execution: SavedExecution}

const prefix = (projectId: string) => productPath(`/api/v1/platform/projects/${encodeURIComponent(projectId)}/design`);

async function request(projectId: string, path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
  const response = await fetch(prefix(projectId) + path, {signal, method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : {'Content-Type':'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) {
    if (response.status === 409) throw new Error('프로젝트 또는 장면 버전이 변경되었습니다. 프로젝트를 다시 열어 확인하세요. (409)');
    throw new Error(`보관된 실행 자료를 처리하지 못했습니다. (${response.status})`);
  }
  return response.json();
}

function execution(value: unknown): SavedExecution {
  const item = value as SavedExecution | null;
  if (!item || !['catalog_id','source_namespace','snapshot_sha256'].every(key => typeof item[key as keyof SavedExecution] === 'string') ||
    !/^[a-f0-9]{64}$/.test(item.snapshot_sha256) ||
    item.execution_state !== 'archived' || typeof item.has_preview !== 'boolean' || typeof item.has_passport !== 'boolean' ||
    (item.execution_id != null && typeof item.execution_id !== 'string') || (item.source_status != null && typeof item.source_status !== 'string') ||
    (item.geometry_ready !== undefined && typeof item.geometry_ready !== 'boolean') ||
    (item.replay_reference !== undefined && (!item.replay_reference || typeof item.replay_reference.source_run_id !== 'string' || item.replay_reference.status !== 'unresolved')))
    throw new Error('보관된 실행 목록 형식이 올바르지 않습니다.');
  return item;
}

function artifact(value: unknown): ExecutionArtifact {
  const item = value as ExecutionArtifact | null;
  if (!item || typeof item.artifact_id !== 'string' || typeof item.role !== 'string' ||
    !['image/png','application/json'].includes(item.media_type) || !Number.isSafeInteger(item.size) || item.size < 0 ||
    typeof item.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.sha256) || typeof item.inline !== 'boolean' ||
    (item.inline && item.media_type !== 'image/png')) throw new Error('보관 자료 응답 형식이 올바르지 않습니다.');
  return item;
}

function page<T>(value: unknown, parse: (item: unknown) => T): ExecutionPage<T> {
  const result = value as ExecutionPage<unknown> | null;
  if (!result || !Array.isArray(result.items)) throw new Error('보관 자료 목록 형식이 올바르지 않습니다.');
  return {...result, items: result.items.map(parse)};
}

export async function projectExecutions(projectId: string, offset: number, signal: AbortSignal) {
  return page(await request(projectId, `/executions?limit=20&offset=${offset}`, signal), execution).items;
}
export async function executionCatalog(projectId: string, offset: number, signal: AbortSignal) {
  return page(await request(projectId, `/archive/executions?limit=20&offset=${offset}`, signal), execution);
}
export async function attachExecution(projectId: string, catalogId: string, revision: number, signal: AbortSignal) {
  await request(projectId, '/executions', signal, {catalog_id: catalogId, scene_revision: revision});
}
export async function executionDetail(projectId: string, catalogId: string, offset: number, signal: AbortSignal): Promise<ExecutionDetail> {
  const value = await request(projectId, `/executions/${encodeURIComponent(catalogId)}?limit=20&offset=${offset}`, signal);
  const result = value as ExecutionDetail;
  const summary = execution(result?.execution);
  if (summary.catalog_id !== catalogId) throw new Error('요청한 실행 보존본과 응답이 일치하지 않습니다.');
  return {...page(value, artifact), execution: summary};
}
export function executionArtifactUrl(projectId: string, catalogId: string, artifactId: string, download = false) {
  return prefix(projectId) + `/executions/${encodeURIComponent(catalogId)}/artifacts/${encodeURIComponent(artifactId)}${download ? '/download' : ''}`;
}
