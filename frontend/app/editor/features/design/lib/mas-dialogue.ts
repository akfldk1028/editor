/**
 * mas-dialogue.ts: Frontend data layer and adapter for Multi-Agent System (MAS) dialogues.
 * Provides types, API fetchers, converters to AGLightMessage, and resilient fallbacks.
 */
import type { AGLightMessage } from '../components/ag-light-flow/types';

export interface MASParticipant {
  agent_id: string;
  name: string;
  port: number;
  role: string;
  tone: 'law' | 'masterplan' | 'mass' | 'critic' | 'orchestrator';
  endpoint?: string;
}

export interface MASDialogueMessage {
  id: string;
  step: number;
  timestamp: string;
  from_agent: string;
  to_agent: string;
  sender_title: string;
  sender_role: string;
  action_type:
    | 'limits_query'
    | 'limits_reply'
    | 'context_resolve'
    | 'synthesis_complete'
    | 'compliance_query'
    | 'compliance_verdict'
    | 'critique'
    | 'info';
  title: string;
  message: string;
  payload?: Record<string, unknown>;
  status: 'info' | 'pass' | 'check' | 'fail';
}

export interface MASCollaborationTranscript {
  benchmark: string;
  session_id: string;
  pnu: string;
  parcel_address: string;
  timestamp: string;
  participants: MASParticipant[];
  messages: MASDialogueMessage[];
  verdict: string;
  metrics?: Record<string, unknown>;
  elapsed_seconds: number;
}

function emptyTranscript(pnu: string, verdict: string): MASCollaborationTranscript {
  return { benchmark: 'Editor project run', session_id: '', pnu, parcel_address: '',
    timestamp: '', participants: [], messages: [], verdict, elapsed_seconds: 0 };
}

export async function fetchMASDialogue(pnu?: string | null): Promise<MASCollaborationTranscript> {
  const query = new URLSearchParams(window.location.search);
  const projectId = query.get('project_id');
  const runId = query.get('run_id');
  if (!projectId || !runId) return emptyTranscript(pnu || '', 'Project and run not selected');
  try {
    const [{ listProjects, getRun }, { toTranscript }] = await Promise.all([
      import('@/lib/orchestrator-runs/api'), import('./run-transcript'),
    ]);
    const binding = (await listProjects()).find(project => project.project_id === projectId);
    if (!binding) throw new Error('Project binding not found');
    const run = await getRun(projectId, runId);
    if (run.owner_project_id !== binding.owner_project_id || run.branch_id !== binding.branch_id || run.run_id !== runId) {
      throw new Error('Run binding mismatch');
    }
    const transcript = toTranscript(projectId, run);
    return {
      ...emptyTranscript(pnu || '', transcript.verdict), session_id: runId,
      participants: transcript.participants.map(peer => ({ ...peer, port: 0, tone: 'orchestrator' as const })),
      messages: transcript.messages.map(message => ({ ...message, timestamp: '', sender_role: message.transport, action_type: 'info' as const })),
    };
  } catch (error) {
    return emptyTranscript(pnu || '', error instanceof Error ? error.message : 'Dialogue unavailable');
  }
}

export function toAGLightMessages(transcript: MASCollaborationTranscript): AGLightMessage[] {
  return transcript.messages.map((m) => ({
    timestamp: m.timestamp,
    from_agent: m.from_agent,
    to_agent: m.to_agent,
    message: `[${m.title}] ${m.message}`,
    event_type: m.action_type,
    metadata: {
      step: m.step,
      sender_title: m.sender_title,
      sender_role: m.sender_role,
      status: m.status,
      payload: m.payload,
    },
  }));
}
