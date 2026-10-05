/**
 * AgentFlow Type Definitions
 * Ported from AutoGen Studio - shared types for pattern system
 */

import type { Edge, Node } from '@xyflow/react'

// Shared participant interface (used by AgentFlow + layout-generator)
export interface Participant {
  config?: { name?: string }
  label?: string
  description?: string
  agent_type?: string
}

// Pattern types matching AutoGen Studio team providers
export type PatternType =
  | 'sequential'
  | 'selector'
  | 'handoff'
  | 'debate'
  | 'reflection'
  | 'unknown'

export type LayoutType =
  | 'chain' // Linear: A -> B -> C
  | 'hub-spoke' // Central hub + radial agents
  | 'mesh' // Full interconnection (Swarm)
  | 'tree' // Hierarchical layers
  | 'fork-join' // Fan-out then merge
  | 'ring' // Circular with voting (Debate)

export type RunStatus =
  | 'created'
  | 'active'
  | 'complete'
  | 'error'
  | 'stopped'
  | 'awaiting_input'
  | 'timeout'

export type NodeType = 'agent' | 'user' | 'end'

export interface AgentNodeData {
  type: NodeType
  label: string
  agentType?: string
  description?: string
  isActive?: boolean
  status?: RunStatus | null
  reason?: string | null
  draggable: boolean
  isHub?: boolean
  hubType?: string
  color?: string
  /** Truncated last message from this agent (live mode) */
  lastMessage?: string
}

export interface CustomEdgeData extends Record<string, unknown> {
  label?: string
  messages?: unknown[]
  routingType?: 'primary' | 'secondary'
  bidirectionalPair?: string
  onClick?: () => void
}

export interface PatternVisual {
  layout: LayoutType
  centerNodeType?: 'selector' | 'supervisor' | 'aggregator' | 'triage'
  edgeStyle: 'solid' | 'dashed' | 'animated'
  bidirectional: boolean
  showCrossConnections: boolean
  primaryColor: string
  secondaryColor: string
  icon: string
}

export interface PatternDefinition {
  id: string
  name: string
  description: string
  visual: PatternVisual
}

export interface PatternLayoutResult {
  nodes: Node[]
  edges: CustomEdge[]
}

// Edge type alias
export type CustomEdge = Edge<CustomEdgeData>

// Node dimensions
export const NODE_DIMENSIONS = {
  default: { width: 170, height: 100 },
  end: { width: 170, height: 80 },
}

// --- Node Creators ---

export const createAgentNode = (
  id: string,
  label: string,
  agentType: string,
  description: string,
  position: { x: number; y: number },
  isActive: boolean,
  isProcessing: boolean,
): Node => ({
  id,
  type: 'agentNode',
  position,
  data: {
    type: 'agent',
    label,
    agentType,
    description,
    isActive,
    status: null,
    reason: null,
    draggable: !isProcessing,
  } satisfies AgentNodeData,
})

export const createUserNode = (
  position: { x: number; y: number },
  isActive: boolean,
  isProcessing: boolean,
): Node => ({
  id: 'user',
  type: 'agentNode',
  position,
  data: {
    type: 'user',
    label: 'User',
    agentType: 'user',
    description: 'Human user',
    isActive,
    status: null,
    reason: null,
    draggable: !isProcessing,
  } satisfies AgentNodeData,
})

export const createEndNode = (
  position: { x: number; y: number },
  status?: string,
  reason?: string,
): Node => ({
  id: 'end',
  type: 'agentNode',
  position,
  data: {
    type: 'end',
    label: 'End',
    status: (status as RunStatus) ?? null,
    reason: reason ?? null,
    agentType: '',
    description: '',
    isActive: false,
    draggable: false,
  } satisfies AgentNodeData,
})

const HUB_TYPE_LABELS = {
  selector: 'LLM Selector',
  supervisor: 'Supervisor',
  aggregator: 'Aggregator',
  triage: 'Triage',
}

export const createHubNode = (
  id: string,
  name: string,
  hubType: 'selector' | 'supervisor' | 'aggregator' | 'triage',
  visual: PatternVisual,
  position: { x: number; y: number },
  isActive: boolean,
  isProcessing: boolean,
): Node => {
  return {
    id,
    type: 'agentNode',
    position,
    data: {
      type: 'agent',
      label: name || HUB_TYPE_LABELS[hubType],
      agentType: HUB_TYPE_LABELS[hubType],
      description: HUB_TYPE_LABELS[hubType],
      isActive,
      isHub: true,
      hubType,
      color: visual.primaryColor,
      draggable: !isProcessing,
    } satisfies AgentNodeData,
  }
}

export const createEdge = (
  id: string,
  source: string,
  target: string,
  options: {
    animated?: boolean
    stroke?: string
    strokeWidth?: number
    strokeDasharray?: string
    opacity?: number
    label?: string
    routingType?: 'primary' | 'secondary'
  } = {},
): CustomEdge => ({
  id,
  source,
  target,
  type: 'custom',
  animated: options.animated ?? false,
  data: {
    label: options.label ?? '',
    messages: [],
    routingType: options.routingType,
  },
  style: {
    stroke: options.stroke ?? '#2563eb',
    strokeWidth: options.strokeWidth ?? 1,
    strokeDasharray: options.strokeDasharray,
    opacity: options.opacity ?? 1,
  },
})

// --- Pattern to Provider mapping (shared by TeamCreateDialog + useTeamEditor) ---

export function patternToProvider(pattern: PatternType): string {
  switch (pattern) {
    case 'sequential':
      return 'autogen_agentchat.teams.RoundRobinGroupChat'
    case 'selector':
      return 'autogen_agentchat.teams.SelectorGroupChat'
    case 'handoff':
      return 'autogen_agentchat.teams.Swarm'
    case 'debate':
      return 'autogen_agentchat.teams.SelectorGroupChat'
    case 'reflection':
      return 'autogen_agentchat.teams.RoundRobinGroupChat'
    default:
      return 'autogen_agentchat.teams.RoundRobinGroupChat'
  }
}

// --- Pattern Detection ---

export const PATTERN_LABELS: Record<
  PatternType,
  { label: string; color: string; description: string }
> = {
  sequential: {
    label: 'Sequential',
    color: '#3b82f6',
    description: 'Agents take turns in fixed order',
  },
  selector: {
    label: 'Selector',
    color: '#8b5cf6',
    description: 'Central router selects best agent',
  },
  handoff: {
    label: 'Handoff',
    color: '#f59e0b',
    description: 'Agents dynamically transfer control',
  },
  debate: { label: 'Debate', color: '#ef4444', description: 'Agents argue different perspectives' },
  reflection: {
    label: 'Reflection',
    color: '#22c55e',
    description: 'Iterative improvement through feedback',
  },
  unknown: { label: 'Custom', color: '#6b7280', description: 'Custom team configuration' },
}

// Built-in pattern definitions with visual config
export const PATTERN_DEFINITIONS: Record<string, PatternDefinition> = {
  sequential: {
    id: 'sequential',
    name: 'Sequential',
    description: 'Agents take turns in fixed order',
    visual: {
      layout: 'chain',
      edgeStyle: 'solid',
      bidirectional: false,
      showCrossConnections: false,
      primaryColor: '#3b82f6',
      secondaryColor: '#93c5fd',
      icon: 'arrow-right',
    },
  },
  selector: {
    id: 'selector',
    name: 'Selector',
    description: 'Central LLM selects best agent per turn',
    visual: {
      layout: 'hub-spoke',
      centerNodeType: 'selector',
      edgeStyle: 'solid',
      bidirectional: true,
      showCrossConnections: false,
      primaryColor: '#8b5cf6',
      secondaryColor: '#c4b5fd',
      icon: 'target',
    },
  },
  handoff: {
    id: 'handoff',
    name: 'Handoff (Swarm)',
    description: 'Agents dynamically transfer control',
    visual: {
      layout: 'mesh',
      centerNodeType: 'triage',
      edgeStyle: 'dashed',
      bidirectional: true,
      showCrossConnections: true,
      primaryColor: '#f59e0b',
      secondaryColor: '#fcd34d',
      icon: 'shuffle',
    },
  },
  debate: {
    id: 'debate',
    name: 'Debate',
    description: 'Agents argue perspectives, judge decides',
    visual: {
      layout: 'ring',
      edgeStyle: 'dashed',
      bidirectional: false,
      showCrossConnections: true,
      primaryColor: '#ef4444',
      secondaryColor: '#fca5a5',
      icon: 'messages-square',
    },
  },
  reflection: {
    id: 'reflection',
    name: 'Reflection',
    description: 'Generator creates, critic reviews iteratively',
    visual: {
      layout: 'chain',
      edgeStyle: 'solid',
      bidirectional: true,
      showCrossConnections: false,
      primaryColor: '#22c55e',
      secondaryColor: '#86efac',
      icon: 'repeat',
    },
  },
}
