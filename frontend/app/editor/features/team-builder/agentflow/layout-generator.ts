/**
 * Layout Generator - 6 layout types for agent team patterns
 * Ported from AutoGen Studio layout-generator.ts
 */

import type { Node } from '@xyflow/react'
import type {
  CustomEdge,
  LayoutType,
  Participant,
  PatternDefinition,
  PatternLayoutResult,
  PatternVisual,
} from './types'
import {
  NODE_DIMENSIONS,
  createAgentNode,
  createEdge,
  createEndNode,
  createHubNode,
  createUserNode,
} from './types'

/** Max agents for O(n²) cross-connection edges to avoid perf issues */
const MAX_CROSS_CONNECTION_AGENTS = 8

const CANVAS = {
  centerX: 500,
  centerY: 320,
  radius: 300,
  nodeSpacing: 280,
}

// --- Chain Layout (Sequential / Reflection) ---

function generateChainLayout(
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

// --- Hub-Spoke Layout (Selector / Supervisor) ---

function generateHubSpokeLayout(
  participants: Participant[],
  visual: PatternVisual,
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const nodes: Node[] = []
  const edges: CustomEdge[] = []

  nodes.push(
    createUserNode(
      { x: 50, y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2 },
      activeAgents.has('user'),
      isProcessing,
    ),
  )

  const hubId = visual.centerNodeType ?? 'hub'
  nodes.push(
    createHubNode(
      hubId,
      '',
      visual.centerNodeType ?? 'selector',
      visual,
      {
        x: CANVAS.centerX - NODE_DIMENSIONS.default.width / 2,
        y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2,
      },
      true,
      isProcessing,
    ),
  )

  edges.push(
    createEdge('user-to-hub', 'user', hubId, {
      stroke: '#2563eb',
      strokeWidth: 2,
      animated: activeAgents.size > 0,
    }),
  )

  const startAngle = -Math.PI / 2.5
  const endAngle = Math.PI / 2.5
  const angleStep =
    participants.length > 1 ? (endAngle - startAngle) / (participants.length - 1) : 0

  participants.forEach((p, i) => {
    const name = p.config?.name ?? `agent-${i}`
    const angle = participants.length === 1 ? 0 : startAngle + i * angleStep
    const x = CANVAS.centerX + CANVAS.radius * Math.cos(angle) - NODE_DIMENSIONS.default.width / 2
    const y = CANVAS.centerY + CANVAS.radius * Math.sin(angle) - NODE_DIMENSIONS.default.height / 2
    const active = activeAgents.has(name)

    nodes.push(
      createAgentNode(
        name,
        name,
        p.label ?? '',
        p.description ?? '',
        { x, y },
        active,
        isProcessing,
      ),
    )

    edges.push(
      createEdge(`hub-to-${name}`, hubId, name, {
        animated: active && isProcessing,
        stroke: active ? visual.primaryColor : '#6b7280',
        strokeWidth: active ? 2 : 1,
        opacity: active ? 1 : 0.4,
        label: active && visual.centerNodeType === 'selector' ? 'selected' : '',
      }),
    )

    if (visual.bidirectional) {
      edges.push(
        createEdge(`${name}-to-hub`, name, hubId, {
          stroke: active ? visual.secondaryColor : '#6b7280',
          strokeWidth: 1,
          strokeDasharray: '5,5',
          opacity: active ? 0.7 : 0.2,
          routingType: 'secondary',
        }),
      )
    }
  })

  if (isComplete) {
    nodes.push(
      createEndNode(
        {
          x: CANVAS.centerX + CANVAS.radius + 100,
          y: CANVAS.centerY - NODE_DIMENSIONS.end.height / 2,
        },
        runStatus,
      ),
    )
    edges.push(
      createEdge('hub-to-end', hubId, 'end', {
        stroke: runStatus === 'complete' ? '#22c55e' : '#ef4444',
        strokeWidth: 2,
      }),
    )
  }

  return { nodes, edges }
}

// --- Mesh Layout (Swarm / Handoff) ---

function generateMeshLayout(
  participants: Participant[],
  visual: PatternVisual,
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const nodes: Node[] = []
  const edges: CustomEdge[] = []

  nodes.push(
    createUserNode(
      { x: 50, y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2 },
      activeAgents.has('user'),
      isProcessing,
    ),
  )

  const triageName = participants[0]?.config?.name ?? 'triage'
  const otherAgents = participants.slice(1)

  nodes.push(
    createHubNode(
      triageName,
      triageName,
      'triage',
      visual,
      {
        x: CANVAS.centerX - NODE_DIMENSIONS.default.width / 2,
        y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2,
      },
      activeAgents.has(triageName),
      isProcessing,
    ),
  )

  edges.push(
    createEdge('user-to-triage', 'user', triageName, {
      stroke: '#2563eb',
      strokeWidth: 2,
      animated: activeAgents.has(triageName),
    }),
  )

  const angleStep = (2 * Math.PI) / Math.max(1, otherAgents.length)
  const startAngle = -Math.PI / 2

  otherAgents.forEach((p, i) => {
    const name = p.config?.name ?? `agent-${i + 1}`
    const angle = startAngle + i * angleStep
    const x = CANVAS.centerX + CANVAS.radius * Math.cos(angle) - NODE_DIMENSIONS.default.width / 2
    const y = CANVAS.centerY + CANVAS.radius * Math.sin(angle) - NODE_DIMENSIONS.default.height / 2
    const active = activeAgents.has(name)

    nodes.push(
      createAgentNode(
        name,
        name,
        p.label ?? '',
        p.description ?? '',
        { x, y },
        active,
        isProcessing,
      ),
    )

    edges.push(
      createEdge(`${triageName}-to-${name}`, triageName, name, {
        animated: active && isProcessing,
        stroke: active ? visual.primaryColor : '#6b7280',
        strokeWidth: active ? 2 : 1,
        strokeDasharray: visual.edgeStyle === 'dashed' ? '8,4' : undefined,
        opacity: active ? 1 : 0.4,
        label: active ? 'handoff' : '',
      }),
    )

    edges.push(
      createEdge(`${name}-to-${triageName}`, name, triageName, {
        stroke: active ? visual.secondaryColor : '#6b7280',
        strokeWidth: 1,
        strokeDasharray: '5,5',
        opacity: active ? 0.8 : 0.2,
        routingType: 'secondary',
      }),
    )
  })

  // Cross-agent mesh connections (capped to avoid O(n²) perf issues)
  if (
    visual.showCrossConnections &&
    otherAgents.length > 1 &&
    otherAgents.length <= MAX_CROSS_CONNECTION_AGENTS
  ) {
    otherAgents.forEach((p1, i) => {
      otherAgents.forEach((p2, j) => {
        if (i < j) {
          const a1 = p1.config?.name ?? `agent-${i + 1}`
          const a2 = p2.config?.name ?? `agent-${j + 1}`
          if (activeAgents.has(a1) && activeAgents.has(a2)) {
            edges.push(
              createEdge(`${a1}-mesh-${a2}`, a1, a2, {
                stroke: '#a855f7',
                strokeWidth: 1,
                strokeDasharray: '3,3',
                opacity: 0.5,
              }),
            )
          }
        }
      })
    })
  }

  if (isComplete) {
    nodes.push(
      createEndNode(
        {
          x: CANVAS.centerX + CANVAS.radius + 100,
          y: CANVAS.centerY - NODE_DIMENSIONS.end.height / 2,
        },
        runStatus,
      ),
    )
    const lastActive = [...activeAgents].filter((a) => a !== 'user').pop()
    if (lastActive) {
      edges.push(
        createEdge(`${lastActive}-to-end`, lastActive, 'end', {
          stroke: runStatus === 'complete' ? '#22c55e' : '#ef4444',
          strokeWidth: 2,
        }),
      )
    }
  }

  return { nodes, edges }
}

// --- Ring Layout (Debate) ---

function generateRingLayout(
  participants: Participant[],
  visual: PatternVisual,
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const nodes: Node[] = []
  const edges: CustomEdge[] = []

  nodes.push(
    createUserNode(
      { x: 50, y: CANVAS.centerY - NODE_DIMENSIONS.default.height / 2 },
      activeAgents.has('user'),
      isProcessing,
    ),
  )

  if (participants.length === 0) return { nodes, edges }

  const angleStep = (2 * Math.PI) / participants.length
  const startAngle = -Math.PI / 2

  participants.forEach((p, i) => {
    const name = p.config?.name ?? `agent-${i}`
    const angle = startAngle + i * angleStep
    const x =
      CANVAS.centerX + CANVAS.radius * 0.8 * Math.cos(angle) - NODE_DIMENSIONS.default.width / 2
    const y =
      CANVAS.centerY + CANVAS.radius * 0.8 * Math.sin(angle) - NODE_DIMENSIONS.default.height / 2

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
  })

  const firstAgent = participants[0]?.config?.name ?? 'agent-0'
  edges.push(
    createEdge('user-to-first', 'user', firstAgent, {
      stroke: '#2563eb',
      strokeWidth: 2,
      animated: activeAgents.has(firstAgent),
    }),
  )

  // All-to-all debate connections (capped to avoid O(n²) perf issues)
  if (visual.showCrossConnections && participants.length <= MAX_CROSS_CONNECTION_AGENTS) {
    participants.forEach((p1, i) => {
      participants.forEach((p2, j) => {
        if (i < j) {
          const a1 = p1.config?.name ?? `agent-${i}`
          const a2 = p2.config?.name ?? `agent-${j}`
          const bothActive = activeAgents.has(a1) && activeAgents.has(a2)

          edges.push(
            createEdge(`${a1}-debate-${a2}`, a1, a2, {
              stroke: bothActive ? visual.primaryColor : '#6b7280',
              strokeWidth: bothActive ? 2 : 1,
              strokeDasharray: '4,4',
              opacity: bothActive ? 0.8 : 0.3,
            }),
          )
        }
      })
    })
  }

  if (isComplete) {
    nodes.push(
      createEndNode(
        {
          x: CANVAS.centerX + CANVAS.radius + 100,
          y: CANVAS.centerY - NODE_DIMENSIONS.end.height / 2,
        },
        runStatus,
      ),
    )
    const lastActive = [...activeAgents].filter((a) => a !== 'user').pop()
    if (lastActive) {
      edges.push(
        createEdge(`${lastActive}-to-end`, lastActive, 'end', {
          stroke: runStatus === 'complete' ? '#22c55e' : '#ef4444',
          strokeWidth: 2,
        }),
      )
    }
  }

  return { nodes, edges }
}

// --- Fork-Join Layout (Parallel / Mixture of Agents) ---

function generateForkJoinLayout(
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

function generateTreeLayout(
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

// --- Main Router ---

export function generateLayoutFromPattern(
  pattern: PatternDefinition,
  participants: Participant[],
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const generators: Record<LayoutType, () => PatternLayoutResult> = {
    chain: () =>
      generateChainLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    'hub-spoke': () =>
      generateHubSpokeLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    mesh: () =>
      generateMeshLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    'fork-join': () =>
      generateForkJoinLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    tree: () =>
      generateTreeLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    ring: () =>
      generateRingLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
  }

  const gen = generators[pattern.visual.layout]
  return gen
    ? gen()
    : generateChainLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      )
}
