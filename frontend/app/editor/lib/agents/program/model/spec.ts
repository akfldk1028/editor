import type { AgentSpec } from '../../spec'

/** Program Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'program',
  name: 'Program Agent',
  tools: { program_from_brief: '프로그램 번역' },
}
