import type { AgentSpec } from '../../spec'

/** DesignIntent Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'design_intent',
  name: 'DesignIntent Agent',
  aliases: ['design-intent'],
}
