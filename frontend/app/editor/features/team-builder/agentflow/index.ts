// Light exports (no xyflow runtime dependency)
export { PATTERN_DEFINITIONS, PATTERN_LABELS, patternToProvider } from './types'
export type { Participant, PatternType } from './types'

// Heavy export (pulls in @xyflow/react + d3 + dagre)
// Use lazy(() => import('./agentflow')) for code-splitting
export { default as AgentFlow, detectPatternType } from './AgentFlow'
export type { AgentFlowProps } from './AgentFlow'
