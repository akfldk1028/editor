import type { Hop } from '@/lib/orchestrator-runs/types'

import type { LedgerMessage } from './types'

/** The text of a GenAI message list (`[{role, parts:[{type:'text', content}]}]`). */
export const hopText = (messages: Hop['input_messages']): string =>
  (messages ?? []).flatMap((message) => message.parts ?? []).filter((part) => part.type === 'text').map((part) => part.content).join('')

/** The A2A state word a recorded call ended in, as the record's `state` the flow already reads. */
const stateOf = (hop: Hop): string => {
  if (!hop.ts_end) return 'running'
  if (hop.state) return hop.state
  return hop.status === 'OK' ? 'succeeded' : hop.status === 'ERROR' ? 'failed' : 'running'
}

/**
 * The ledger's rows as the messages the flow draws: each call is a request from its caller to its callee (what was
 * asked) and, once it ended, the callee's response (what came back). A call still running shows as a running request.
 * `start_run` rows are the person's request to the Orchestrator that opened a run.
 */
export function fromHops(hops: readonly Hop[]): LedgerMessage[] {
  const out: LedgerMessage[] = []
  for (const hop of hops) {
    const base = { tool: hop.tool ?? '', transport: 'a2a' as const, a2a_task_id: hop.task_id ?? null }
    const input = hopText(hop.input_messages)
    const output = hopText(hop.output_messages)
    const state = stateOf(hop)
    out.push({ ...base, truncated: !!hop.texts_clipped?.input, id: `hop:${hop.id}:request`, step: 0, direction: 'request', from: hop.from_agent, to: hop.to_agent, state, text: input || (hop.operation === 'start_run' ? '실행 시작' : ''), at: Date.parse(hop.ts_start) || 0 })
    if (hop.ts_end && (output || hop.status === 'ERROR')) {
      out.push({ ...base, truncated: !!hop.texts_clipped?.output, id: `hop:${hop.id}:response`, step: 0, direction: 'response', from: hop.to_agent, to: hop.from_agent, state: hop.status === 'ERROR' ? 'failed' : state,
        text: output || (hop.error_type ? `{"error": ${JSON.stringify(hop.error_type)}}` : ''), at: Date.parse(hop.ts_end) || 0 })
    }
  }
  return out.map((message, index) => ({ ...message, step: index + 1 }))
}

/** Which calls the panel asks for: this conversation's (and the runs it started), or one run named by the opener. */
export type LedgerScope = { conversation_id: string } | { run_id: string }

export const scopeQuery = (scope: LedgerScope): string =>
  'conversation_id' in scope ? `conversation_id=${encodeURIComponent(scope.conversation_id)}` : `run_id=${encodeURIComponent(scope.run_id)}`
