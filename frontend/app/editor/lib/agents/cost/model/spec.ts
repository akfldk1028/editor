import type { AgentSpec } from '../../spec'

/** Cost Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'cost',
  name: 'Cost Agent',
}
