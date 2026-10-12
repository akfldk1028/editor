import { listAgentTasks } from '@/lib/orchestrator-runs/api'
import type { AgentTask } from '@/lib/orchestrator-runs/types'

/** The agent's own task records (official A2A ListTasks through the editor door), read once per agent and kept for the panel's life. */
export function agentTaskReader() {
  const cache = new Map<string, Promise<AgentTask[]>>()
  return (agent: string, signal?: AbortSignal): Promise<AgentTask[]> => {
    const cached = cache.get(agent)
    if (cached) return cached
    const pending = listAgentTasks(agent, signal).catch((error: unknown) => { cache.delete(agent); throw error })
    cache.set(agent, pending)
    return pending
  }
}
