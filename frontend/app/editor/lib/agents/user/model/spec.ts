import type { AgentSpec } from '../../spec'

/** 사용자 as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'user',
  name: '사용자',
}
