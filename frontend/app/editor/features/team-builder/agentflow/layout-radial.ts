/**
 * Radial layouts - hub-spoke, mesh, ring
 * Ported from AutoGen Studio layout-generator.ts
 */

import type { Node } from '@xyflow/react'
import { CANVAS, MAX_CROSS_CONNECTION_AGENTS } from './layout-shared'
import type { CustomEdge, Participant, PatternLayoutResult, PatternVisual } from './types'
import {
  createAgentNode,
  createEdge,
  createEndNode,
  createHubNode,
  createUserNode,
  NODE_DIMENSIONS,
} from './types'

// --- Hub-Spoke Layout (Selector / Supervisor) ---

export function generateHubSpokeLayout(
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

export function generateMeshLayout(
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

export function generateRingLayout(
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
