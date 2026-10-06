/**
 * Linear layouts - chain, fork-join, tree
 * Ported from AutoGen Studio layout-generator.ts
 */

import type { Node } from '@xyflow/react'
import { CANVAS } from './layout-shared'
import type { CustomEdge, Participant, PatternLayoutResult, PatternVisual } from './types'
import {
  createAgentNode,
  createEdge,
  createEndNode,
  createHubNode,
  createUserNode,
  NODE_DIMENSIONS,
} from './types'

// --- Chain Layout (Sequential / Reflection) ---

export function generateChainLayout(
  participants: Participant[],
  visual: PatternVisual,
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const nodes: Node[] = []
  const edges: CustomEdge[] = []
  const startX = 50
  const y = CANVAS.centerY - NODE_DIMENSIONS.default.height / 2

  nodes.push(createUserNode({ x: startX, y }, activeAgents.has('user'), isProcessing))

  participants.forEach((p, i) => {
    const name = p.config?.name ?? `agent-${i}`
    const x = startX + (i + 1) * CANVAS.nodeSpacing

    nodes.push(
      createAgentNode(
        name,
        name,
        p.label ?? '',
        p.description ?? '',
        { x, y },
        activeAgents.has(name),
        isProcessing,
      ),
    )

    const prevId = i === 0 ? 'user' : (participants[i - 1]?.config?.name ?? `agent-${i - 1}`)
    const active = activeAgents.has(name)

    edges.push(
      createEdge(`${prevId}-to-${name}`, prevId, name, {
        stroke: active ? visual.primaryColor : '#6b7280',
        strokeWidth: active ? 2 : 1,
        animated: active && isProcessing,
      }),
    )

    // Reflection loop-back for 2-agent patterns
    if (visual.bidirectional && i === participants.length - 1 && participants.length === 2) {
      edges.push(
        createEdge(`${name}-loop`, name, participants[0]?.config?.name ?? 'agent-0', {
          stroke: visual.secondaryColor,
          strokeWidth: 1,
          strokeDasharray: '5,5',
          label: 'revise',
          routingType: 'secondary',
        }),
      )
    }
  })

  if (isComplete) {
    const lastName =
      participants[participants.length - 1]?.config?.name ?? `agent-${participants.length - 1}`
    const endX = startX + (participants.length + 1) * CANVAS.nodeSpacing
    nodes.push(createEndNode({ x: endX, y }, runStatus))
    edges.push(
      createEdge(`${lastName}-to-end`, lastName, 'end', {
        stroke: runStatus === 'complete' ? '#22c55e' : '#ef4444',
        strokeWidth: 2,
      }),
    )
  }

  return { nodes, edges }
}

// --- Fork-Join Layout (Parallel / Mixture of Agents) ---

export function generateForkJoinLayout(
  participants: Participant[],
  visual: PatternVisual,
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const nodes: Node[] = []
  const edges: CustomEdge[] = []

  const leftX = 50
  const centerX = CANVAS.centerX
  const rightX = CANVAS.centerX + CANVAS.radius + 50

  nodes.push(
    createUserNode(
      { x: leftX, y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2 },
      activeAgents.has('user'),
      isProcessing,
    ),
  )

  nodes.push(
    createHubNode(
      'aggregator-in',
      'Distribute',
      'aggregator',
      visual,
      { x: leftX + 180, y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2 },
      true,
      isProcessing,
    ),
  )

  edges.push(
    createEdge('user-to-agg', 'user', 'aggregator-in', {
      stroke: '#2563eb',
      strokeWidth: 2,
      animated: isProcessing,
    }),
  )

  const agentSpacing = 180
  const startY = CANVAS.centerY - ((participants.length - 1) * agentSpacing) / 2

  participants.forEach((p, i) => {
    const name = p.config?.name ?? `agent-${i}`
    const y = startY + i * agentSpacing - NODE_DIMENSIONS.default.height / 2
    const active = activeAgents.has(name)

    nodes.push(
      createAgentNode(
        name,
        name,
        p.label ?? '',
        p.description ?? '',
        { x: centerX, y },
        active,
        isProcessing,
      ),
    )

    edges.push(
      createEdge(`agg-to-${name}`, 'aggregator-in', name, {
        stroke: active ? visual.primaryColor : '#6b7280',
        strokeWidth: active ? 2 : 1,
        animated: active && isProcessing,
      }),
    )

    edges.push(
      createEdge(`${name}-to-agg-out`, name, 'aggregator-out', {
        stroke: active ? visual.secondaryColor : '#6b7280',
        strokeWidth: active ? 2 : 1,
        animated: active && isProcessing,
      }),
    )
  })

  nodes.push(
    createHubNode(
      'aggregator-out',
      'Aggregate',
      'aggregator',
      visual,
      { x: rightX, y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2 },
      activeAgents.size > 1,
      isProcessing,
    ),
  )

  if (isComplete) {
    nodes.push(
      createEndNode(
        { x: rightX + 180, y: CANVAS.centerY - NODE_DIMENSIONS.end.height / 2 },
        runStatus,
      ),
    )
    edges.push(
      createEdge('agg-out-to-end', 'aggregator-out', 'end', {
        stroke: runStatus === 'complete' ? '#22c55e' : '#ef4444',
        strokeWidth: 2,
      }),
    )
  }

  return { nodes, edges }
}

// --- Tree Layout (Hierarchical) ---

export function generateTreeLayout(
  participants: Participant[],
  visual: PatternVisual,
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const nodes: Node[] = []
  const edges: CustomEdge[] = []

  const leaderName = participants[0]?.config?.name ?? 'leader'
  const workers = participants.slice(1)

  nodes.push(createUserNode({ x: 50, y: 50 }, activeAgents.has('user'), isProcessing))

  nodes.push(
    createHubNode(
      leaderName,
      leaderName,
      'supervisor',
      visual,
      { x: 250, y: 50 },
      activeAgents.has(leaderName),
      isProcessing,
    ),
  )

  edges.push(
    createEdge('user-to-leader', 'user', leaderName, {
      stroke: '#2563eb',
      strokeWidth: 2,
      animated: activeAgents.has(leaderName),
    }),
  )

  const workerY = 320
  const workerSpacing = 250
  const startX = CANVAS.centerX - ((workers.length - 1) * workerSpacing) / 2

  workers.forEach((p, i) => {
    const name = p.config?.name ?? `worker-${i}`
    const x = startX + i * workerSpacing
    const active = activeAgents.has(name)

    nodes.push(
      createAgentNode(
        name,
        name,
        p.label ?? '',
        p.description ?? '',
        { x, y: workerY },
        active,
        isProcessing,
      ),
    )

    edges.push(
      createEdge(`${leaderName}-to-${name}`, leaderName, name, {
        stroke: active ? visual.primaryColor : '#6b7280',
        strokeWidth: active ? 2 : 1,
        animated: active && isProcessing,
      }),
    )

    if (visual.bidirectional) {
      edges.push(
        createEdge(`${name}-to-${leaderName}`, name, leaderName, {
          stroke: active ? visual.secondaryColor : '#6b7280',
          strokeWidth: 1,
          strokeDasharray: '5,5',
          opacity: active ? 0.7 : 0.3,
          routingType: 'secondary',
        }),
      )
    }
  })

  if (isComplete) {
    nodes.push(createEndNode({ x: 500, y: 50 }, runStatus))
    edges.push(
      createEdge('leader-to-end', leaderName, 'end', {
        stroke: runStatus === 'complete' ? '#22c55e' : '#ef4444',
        strokeWidth: 2,
      }),
    )
  }

  return { nodes, edges }
}
