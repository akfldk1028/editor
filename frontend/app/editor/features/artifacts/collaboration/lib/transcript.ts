import { agentForTool } from '@/lib/orchestrator-runs/labels'
import type { LedgerMessage } from '@/lib/ledger'
import type { Communications } from '@/lib/orchestrator-runs/types'

export type { Direction } from '@/lib/ledger'

/** One thing said in a run: the Orchestrator's request to an agent, or that agent's answer. */
export type CollaborationMessage = LedgerMessage

export interface Transcript {
  /** Canonical agent ids in order of appearance; the Orchestrator first whenever anything was said. */
  participants: string[]
  messages: CollaborationMessage[]
  available: boolean
  truncated: boolean
}

export const ORCHESTRATOR = 'orchestrator'
export const UNKNOWN_PEER = '대상 미기록'

/** The run's communications as messages in the order they were recorded: each row is a request and, once answered, a response. */
export function toTranscript(run: Communications): Transcript {
  const participants: string[] = []
  const messages: CollaborationMessage[] = []
  const seen = (id: string) => { if (!participants.includes(id)) participants.push(id) }
  for (const row of run.communications) {
    const peer = agentForTool(row.tool, row.agent) ?? UNKNOWN_PEER
    seen(ORCHESTRATOR)
    seen(peer)
    for (const direction of ['request', 'response'] as const) {
      const text = direction === 'request' ? row.request_text : row.response_text
      if (text === null) continue
      messages.push({
        id: `${row.id}:${direction}`, step: messages.length + 1, direction,
        from: direction === 'request' ? ORCHESTRATOR : peer, to: direction === 'request' ? peer : ORCHESTRATOR,
        tool: row.tool, state: row.state, transport: row.transport, truncated: row.truncated, text, a2a_task_id: row.a2a_task_id ?? null,
      })
    }
  }
  return {
    participants, messages, available: run.communications_available,
    truncated: run.communications_truncated || run.communications.some((row) => row.truncated),
  }
}
