export { AgentConfigPanel } from './components/AgentConfigPanel'
export { JsonView } from './components/JsonView'
export { PatternSelector } from './components/PatternSelector'
// Light agentflow exports (types + pattern utilities, no xyflow dependency)
export { PATTERN_DEFINITIONS, PATTERN_LABELS, patternToProvider } from './agentflow/types'
export type { Participant, PatternType } from './agentflow/types'
// AgentFlow component should be lazy-loaded: lazy(() => import('@/features/team-builder/agentflow'))

// Phase 3b: Edit mode
export { AgentAddDialog } from './components/AgentAddDialog'
export { EditableAgentPanel } from './components/EditableAgentPanel'
export { ModelSelector } from './components/ModelSelector'
export { TerminationEditor } from './components/TerminationEditor'
export { useTeamEditor } from './hooks/useTeamEditor'
