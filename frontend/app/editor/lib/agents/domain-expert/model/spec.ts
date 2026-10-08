import type { AgentSpec } from '../../spec'

/** DomainExpert Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'domain_expert',
  name: 'DomainExpert Agent',
  aliases: ['domain-expert'],
}
