import {parseCommunications,type Communications} from './communications';

export interface RunSummary extends Communications {
  run_id: string; request_id: string; owner_project_id: string; branch_id: string;
  goal: string; status: string; receipt_task_ids: string[]; pending_input: boolean;
}

async function request(path: string, options?: RequestInit) {
  const response = await fetch((process.env.NEXT_PUBLIC_BASE_PATH || '') + '/api/v1/platform' + path, options);
  if (!response.ok) throw new Error(`실행 연결 실패 (${response.status})`);
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
export async function listRuns(projectId: string, signal?: AbortSignal): Promise<RunSummary[]> {
  const values = await request(`/projects/${encodeURIComponent(projectId)}/runs`,{signal});
  if (!Array.isArray(values)) throw new Error('실행 목록 형식이 올바르지 않습니다.');
  return values.map(parseRun);
}
export async function getRun(projectId: string, runId: string, signal?: AbortSignal): Promise<RunSummary> {
  return parseRun(await request(`/runs/${encodeURIComponent(runId)}?project_id=${encodeURIComponent(projectId)}`,{signal}));
}
