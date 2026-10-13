import type { AgentSpec } from '../../spec'

/** DesignIntent Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'design_intent',
  name: 'DesignIntent Agent',
  aliases: ['design-intent'],
  tools: { intent_declare: '설계 의도 기록', intent_check: '설계 의도 점검' },
}
