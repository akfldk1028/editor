import type { AgentSpec } from '../../spec'

/** MasterPlan Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'masterplan',
  name: 'MasterPlan Agent',
  tools: { masterplan_design: '배치 설계' },
}
