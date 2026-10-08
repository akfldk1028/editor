import type { AgentSpec } from '../../spec'

/** Plan Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'plan',
  name: 'Plan Agent',
  aliases: ['planm'],
}
