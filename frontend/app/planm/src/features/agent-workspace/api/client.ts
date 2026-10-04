import type { AgentSummary } from './types';

export async function listAgents(signal?: AbortSignal): Promise<AgentSummary[]> {
  const response = await fetch('/api/v1/platform/agents', { signal });
  if (!response.ok) throw new Error(`에이전트 목록 연결 실패 (${response.status})`);
  const data: unknown = await response.json();
  if (!Array.isArray(data) || !data.every((item) =>
    item && typeof item.agent_id === 'string' && typeof item.label === 'string' &&
    Array.isArray(item.capabilities) && item.capabilities.every((value: unknown) => typeof value === 'string') &&
    typeof item.implementation_status === 'string' && typeof item.connection_status === 'string' &&
    (item.checked_at === null || typeof item.checked_at === 'string') &&
    (item.evidence_ref === null || typeof item.evidence_ref === 'string')
  )) throw new Error('에이전트 목록 응답 형식을 확인할 수 없습니다.');
  return data;
}
