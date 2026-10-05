import { productPath } from '../../../app/product-path';
export interface DesignJob {
  source_id: string;
  job_id: string;
  created_at: string | null;
  source_status: string;
  execution_state: 'archived';
  result_count: number;
  scene_revision?: number;
  data?: Record<string, unknown>;
}

export interface DesignResult {
  source_id: string;
  job_id: string;
  result_pk: number;
  generation: number | null;
  design_id: number | string | null;
  has_mass: boolean;
  execution_state: 'archived';
  outputs: unknown;
  is_feasible: boolean | number | null;
  is_pareto_optimal: boolean | number | null;
  ranking: number | null;
  data?: Record<string, unknown>;
  selected_at?: string;
  scene_id?: string;
  scene_revision?: number;
}

export interface DesignPage<T> {items: T[]; limit: number; offset: number}

function base(projectId: string) {return productPath(`/api/v1/platform/projects/${encodeURIComponent(projectId)}/design`);}
function jobPath(job: Pick<DesignJob, 'source_id' | 'job_id'>) {
  return `/jobs/${encodeURIComponent(job.source_id)}/${encodeURIComponent(job.job_id)}`;
}

async function request(projectId: string, path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
  const response = await fetch(base(projectId) + path, {signal, method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) {
    if (response.status === 409) throw new Error('장면 버전이 변경되었거나 연결된 자료가 다릅니다. 프로젝트를 다시 열어 확인하세요. (409)');
    throw new Error(`저장된 설계 자료를 처리하지 못했습니다. (${response.status})`);
  }
  return response.json();
}

function job(value: unknown): DesignJob {
  const item = value as DesignJob | null;
  if (!item || typeof item.source_id !== 'string' || typeof item.job_id !== 'string' || item.execution_state !== 'archived')
    throw new Error('저장된 작업 응답 형식이 올바르지 않습니다.');
  return item;
}

function result(value: unknown, detail = false): DesignResult {
  const item = value as DesignResult | null;
  if (!item || typeof item.source_id !== 'string' || typeof item.job_id !== 'string' ||
    !Number.isInteger(item.result_pk) || item.execution_state !== 'archived' ||
    (detail && (!item.data || typeof item.data !== 'object' || Array.isArray(item.data))))
    throw new Error('저장된 설계 응답 형식이 올바르지 않습니다.');
  return item;
}

function page<T>(value: unknown, parse: (item: unknown) => T): DesignPage<T> {
  const data = value as DesignPage<unknown> | null;
  if (!data || !Array.isArray(data.items)) throw new Error('저장된 설계 목록 형식이 올바르지 않습니다.');
  return {...data, items: data.items.map(parse)};
}

export async function projectDesignJobs(projectId: string, signal: AbortSignal) {
  return page(await request(projectId, '/jobs', signal), job).items;
}
export async function archivedDesignJobs(projectId: string, offset: number, signal: AbortSignal) {
  return page(await request(projectId, `/archive/jobs?limit=20&offset=${offset}`, signal), job);
}
export async function attachDesignJob(projectId: string, item: DesignJob, revision: number, signal: AbortSignal) {
  await request(projectId, '/jobs', signal, {source_id: item.source_id, job_id: item.job_id, scene_revision: revision});
}
export async function designJobDetail(projectId: string, item: DesignJob, signal: AbortSignal) {
  return job(await request(projectId, jobPath(item), signal));
}
export async function designResults(projectId: string, item: DesignJob, offset: number, signal: AbortSignal) {
  return page(await request(projectId, `${jobPath(item)}/results?limit=20&offset=${offset}`, signal), value => result(value));
}
export async function designResultDetail(projectId: string, item: DesignResult, signal: AbortSignal) {
  return result(await request(projectId, `${jobPath(item)}/results/${item.result_pk}`, signal), true);
}
export async function selectedDesign(projectId: string, signal: AbortSignal) {
  const value = await request(projectId, '/selection', signal);
  return value === null ? null : result(value, true);
}
export async function selectDesign(projectId: string, item: DesignResult, revision: number, signal: AbortSignal) {
  return result(await request(projectId, '/selection', signal,
    {source_id: item.source_id, job_id: item.job_id, result_pk: item.result_pk, scene_revision: revision}), true);
}
