import type { AgentTask } from '@/lib/orchestrator-runs/types'

import type { CollaborationMessage } from './transcript'

/**
 * The agent's own record of a reply the Orchestrator cut: the task whose full reply begins with the recorded
 * text (a cut record is a prefix of the whole; an uncut one is equal). Null when the agent holds no such task —
 * it restarted since, or the reply was another's.
 */
export function fullRecordFor(message: CollaborationMessage, tasks: readonly AgentTask[]): AgentTask | null {
  if (message.direction !== 'response' || !message.text) return null
  const head = message.text.slice(0, 2_000)
  const exact = tasks.find((task) => task.response_text === message.text)
  if (exact) return exact
  const longer = tasks.filter((task) => task.response_text.length > message.text.length && task.response_text.startsWith(head))
  return longer.find((task) => task.tool === message.tool) ?? longer[0] ?? null
}
