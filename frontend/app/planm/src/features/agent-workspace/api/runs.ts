import { productPath } from '../../../app/product-path';
import {parseCommunications,type Communications} from './communications';
import { getProject } from './projects';

export interface RunSummary extends Communications {
  run_id: string; request_id: string; owner_project_id: string; branch_id: string;
  goal: string; status: string; receipt_task_ids: string[]; pending_input: boolean;
}
export interface RunContext {scene_revision: number; source_versions: Record<string,number>}

async function request(path: string, options?: RequestInit) {
  const response = await fetch(productPath('/api/v1/platform' + path), options);
  if (!response.ok) throw new Error(response.status === 503 && options?.method === 'POST'
    ? '요청 응답을 확인하지 못했습니다. 같은 요청으로 다시 확인하거나 실행 이력을 조회하세요.'
    : `실행 연결 실패 (${response.status})`);
  return response.json();
}
function parseRun(value: unknown): RunSummary {
  const item = value as RunSummary | null;
  if (!item || !['run_id','request_id','owner_project_id','branch_id','goal','status'].every(key => typeof item[key as keyof RunSummary] === 'string') ||
    !Array.isArray(item.receipt_task_ids) || !item.receipt_task_ids.every(id => typeof id === 'string') || typeof item.pending_input !== 'boolean') {
    throw new Error('실행 응답 형식이 올바르지 않습니다.');
  }
  return {...item,...parseCommunications(value as Record<string,unknown>)};
}
export async function getRunContext(projectId: string, signal?: AbortSignal): Promise<RunContext> {
  const value = await request(`/projects/${encodeURIComponent(projectId)}/context`,{signal});
  if (!value || !Number.isInteger(value.scene_revision) || !value.source_versions || Array.isArray(value.source_versions) ||
    typeof value.source_versions !== 'object' || !Object.values(value.source_versions).every(v => Number.isInteger(v) && Number(v) >= 0)) throw new Error('원본 버전 응답이 올바르지 않습니다.');
  return value;
}
export async function submitHealth(projectId: string, context: RunContext, key: string): Promise<RunSummary> {
  return parseRun(await request(`/projects/${encodeURIComponent(projectId)}/runs`,{method:'POST',
    headers:{'Content-Type':'application/json','Idempotency-Key':key}, body:JSON.stringify({...context,request:{goal:'health'}})}));
}
export async function listRuns(projectId: string, signal?: AbortSignal): Promise<RunSummary[]> {
  const values = await request(`/projects/${encodeURIComponent(projectId)}/runs`,{signal});
  if (!Array.isArray(values)) throw new Error('실행 목록 형식이 올바르지 않습니다.');
  return values.map(parseRun);
}
export async function getRun(projectId: string, runId: string, signal?: AbortSignal): Promise<RunSummary> {
  const [project, value] = await Promise.all([getProject(projectId, signal),
    request(`/runs/${encodeURIComponent(runId)}?project_id=${encodeURIComponent(projectId)}`,{signal})]);
  const run = parseRun(value);
  if (run.run_id !== runId || run.owner_project_id !== project.owner_project_id || run.branch_id !== project.branch_id ||
      !run.request_id.startsWith(`editor:${projectId}:`)) throw new Error('프로젝트와 실행 연결이 일치하지 않습니다.');
  return run;
}
export function runUrl(projectId: string, runId: string) {
  return productPath(`/runs/${encodeURIComponent(runId)}?project_id=${encodeURIComponent(projectId)}`);
}
