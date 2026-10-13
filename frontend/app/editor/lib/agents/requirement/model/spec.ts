import type { AgentSpec } from '../../spec'

/** Requirement Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'requirement',
  name: 'Requirement Agent',
  tools: { requirement_structure: '요구사항 정리' },
}
