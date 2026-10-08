import type { AgentSpec } from '../../spec'

/** Revision Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'revision',
  name: 'Revision Agent',
  tools: { revision_triage: '재검토 판정' },
}
