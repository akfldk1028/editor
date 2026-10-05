export interface AgentSummary {
  agent_id: string;
  label: string;
  capabilities: string[];
  implementation_status: string;
  connection_status: string;
  checked_at: string | null;
  evidence_ref: string | null;
}

export async function listAgents(signal?: AbortSignal): Promise<AgentSummary[]> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/platform/agents`, { signal });
  if (!response.ok) throw new Error(`에이전트 목록 연결 실패 (${response.status})`);
  const data = await response.json();
  if (!Array.isArray(data) || data.some(row => !row ||
    !['agent_id', 'label', 'implementation_status', 'connection_status'].every(key => typeof row[key] === 'string') ||
    !Array.isArray(row.capabilities) || !row.capabilities.every((v: unknown) => typeof v === 'string') ||
    !['checked_at', 'evidence_ref'].every(key => row[key] === null || typeof row[key] === 'string')) ||
    new Set(data.map(row => row.agent_id)).size !== data.length) throw new Error('에이전트 목록 형식이 올바르지 않습니다.');
  return data;
}
