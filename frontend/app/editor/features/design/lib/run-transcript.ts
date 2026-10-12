import type { RunSummary } from '@/lib/orchestrator-runs/types'

/**
 * The design page's view of an Orchestrator run as a MAS transcript (moved verbatim from the retired
 * features/agent-dialogue/transcript.ts, 2026-10-12). The 협업 artifact owns the current reading
 * (features/artifacts/collaboration/lib/transcript.ts); this stays until the design page is folded in.
 */
export interface MASDialogueMessage {
  id: string;
  step: number;
  from_agent: string;
  to_agent: string;
  sender_title: string;
  title: string;
  message: string;
  payload: Record<string, unknown>;
  status: 'info' | 'check' | 'fail';
  transport: string;
}
export interface MASCollaborationTranscript {
  project_id: string;
  session_id: string;
  verdict: string;
  goal: string;
  pending_input: boolean;
  receipt_task_ids: string[];
  available: boolean;
  truncated: boolean;
  participants: { agent_id: string; name: string; role: string }[];
  messages: MASDialogueMessage[];
}

export function toTranscript(projectId: string, run: RunSummary): MASCollaborationTranscript {
  const participants = new Map<string, { agent_id: string; name: string; role: string }>();
  const messages: MASDialogueMessage[] = [];
  for (const row of run.communications) {
    const peer = row.agent || '대상 미기록';
    participants.set('orchestrator', { agent_id: 'orchestrator', name: 'Orchestrator', role: '실행 담당' });
    participants.set(peer, { agent_id: peer, name: peer, role: row.transport === 'a2a' ? 'A2A 기록 대상' : '전송 방식 미확인' });
    const payload = { task_id: row.task_id, tool: row.tool, state: row.state, transport: row.transport, truncated: row.truncated };
    const status = /failed|error|rejected/.test(row.state) ? 'fail' : /blocked|pending|partial/.test(row.state) ? 'check' : 'info';
    for (const direction of ['request', 'response'] as const) {
      const body = direction === 'request' ? row.request_text : row.response_text;
      if (body === null) continue;
      const from = direction === 'request' ? 'orchestrator' : peer;
      messages.push({ id: `${row.id}:${direction}`, step: messages.length + 1, from_agent: from,
        to_agent: direction === 'request' ? peer : 'orchestrator', sender_title: from,
        title: `${row.tool} · ${direction === 'request' ? '요청' : '응답'} · ${row.state}`,
        message: body, payload, status, transport: row.transport === 'a2a' ? 'A2A 기록' : '전송 방식 미확인' });
    }
  }
  return { project_id: projectId, session_id: run.run_id, verdict: run.status, goal: run.goal,
    pending_input: run.pending_input, receipt_task_ids: run.receipt_task_ids,
    available: run.communications_available, truncated: run.communications_truncated || run.communications.some(row => row.truncated),
    participants: [...participants.values()], messages };
}
