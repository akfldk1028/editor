import type { AgentSpec } from '../../spec'

/** Site Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'site_context',
  name: 'Site Agent',
  aliases: ['site-context', 'site'],
  tools: { site_resolve: '대지 사실 확인' },
}
