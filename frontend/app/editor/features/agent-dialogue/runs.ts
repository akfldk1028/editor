import {parseCommunications,type Communications} from './communications';

export interface RunSummary extends Communications {
  run_id: string; request_id: string; owner_project_id: string; branch_id: string;
  goal: string; status: string; receipt_task_ids: string[]; pending_input: boolean;
  /** W3C trace id (32 hex) of the submission; only the editor's POST answer carries it. */
  trace_id?: string;
}
export interface RunContext { scene_revision: number; source_versions: Record<string, number> }

/** A refused platform call: `status` and the backend `detail` let a caller tell 503 (owner down) from 409/422. */
export class RunRequestError extends Error {
  constructor(message: string, readonly status: number, readonly detail: string | null) { super(message); }
}
/** What the editor door accepts today (schemas/platform.py `RunCreate.supported_request`), minus specialist reviews. */
export type RunRequest = { goal: 'health' } | { goal: 'limits'; pnu: string; building_type?: string };

async function request(path: string, options?: RequestInit) {
  const response = await fetch((process.env.NEXT_PUBLIC_BASE_PATH || '') + '/api/v1/platform' + path, options);
  if (!response.ok) {
    const detail = await response.json().then((v: unknown) => typeof (v as { detail?: unknown })?.detail === 'string'
      ? (v as { detail: string }).detail : null).catch(() => null);
    throw new RunRequestError(options?.method === 'POST' && response.status >= 500
      ? '실행 접수 여부를 확인하지 못했습니다. 같은 요청으로 다시 확인하거나 실행 목록을 조회하세요.'
      : `실행 연결 실패 (${response.status})`, response.status, detail);
  }
  return response.json();
}
export function parseRun(value: unknown): RunSummary {
  const item = value as RunSummary | null;
  if (!item || !['run_id','request_id','owner_project_id','branch_id','goal','status'].every(key => typeof item[key as keyof RunSummary] === 'string') ||
    !Array.isArray(item.receipt_task_ids) || !item.receipt_task_ids.every(id => typeof id === 'string') || typeof item.pending_input !== 'boolean') {
    throw new Error('실행 응답 형식이 올바르지 않습니다.');
  }
  const {trace_id, ...rest} = item;
  return {...rest, ...(typeof trace_id === 'string' && /^[0-9a-f]{32}$/.test(trace_id) ? {trace_id} : {}),
    ...parseCommunications(value as Record<string,unknown>)};
}
export async function listRuns(projectId: string, signal?: AbortSignal): Promise<RunSummary[]> {
  const values = await request(`/projects/${encodeURIComponent(projectId)}/runs`,{signal});
  if (!Array.isArray(values)) throw new Error('실행 목록 형식이 올바르지 않습니다.');
  return values.map(parseRun);
}
export async function getRun(projectId: string, runId: string, signal?: AbortSignal): Promise<RunSummary> {
  return parseRun(await request(`/runs/${encodeURIComponent(runId)}?project_id=${encodeURIComponent(projectId)}`,{signal}));
}

export async function getRunContext(projectId: string, signal?: AbortSignal): Promise<RunContext> {
  const value = await request(`/projects/${encodeURIComponent(projectId)}/context`, { signal });
  if (!value || !Number.isInteger(value.scene_revision) || value.scene_revision < 0 || !value.source_versions ||
    typeof value.source_versions !== 'object' || Array.isArray(value.source_versions) ||
    !Object.values(value.source_versions).every(v => Number.isInteger(v) && Number(v) >= 0)) {
    throw new Error('원본 버전 응답이 올바르지 않습니다.');
  }
  return value;
}

export async function submitRun(projectId: string, context: RunContext, key: string, body: RunRequest, signal?: AbortSignal): Promise<RunSummary> {
  return parseRun(await request(`/projects/${encodeURIComponent(projectId)}/runs`, { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify({ ...context, request: body }),
  }));
}
export function submitHealth(projectId: string, context: RunContext, key: string, signal?: AbortSignal): Promise<RunSummary> {
  return submitRun(projectId, context, key, { goal: 'health' }, signal);
}
