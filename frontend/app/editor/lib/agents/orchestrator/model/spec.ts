import type { AgentSpec } from '../../spec'

/** Orchestrator Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'orchestrator',
  name: 'Orchestrator Agent',
}
