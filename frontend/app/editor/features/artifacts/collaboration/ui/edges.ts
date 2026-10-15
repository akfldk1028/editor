/**
 * One theme for every line on the collaboration canvas: a request in the accent (dashed, moving while it runs),
 * an answer in green, the person's line in ink, the order line dotted — whichever view draws it (에이전트 or 패턴).
 */
import { type Edge, MarkerType } from '@xyflow/react'

import type { GraphEdge } from '../lib/graph'

const arrow = (back: boolean) => ({ type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' })

/** A React Flow edge with the smoothstep path options (`Edge` itself does not name them). */
export type FlowEdge = Edge & { pathOptions?: { borderRadius?: number; offset?: number } }

export function toFlowEdge(edge: GraphEdge): FlowEdge {
  const spoken = edge.kind === 'request' || edge.kind === 'response'
  const back = edge.kind === 'response'
  const className = `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}${edge.running ? ' collab-edge-running' : ''}`
  if (edge.sourceHandle && edge.targetHandle) {
    // The wide flow (and the pattern view): each line names the handles it leaves and enters by.
    return {
      id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle, type: 'smoothstep', pathOptions: { borderRadius: 12, offset: 18 }, animated: spoken, className,
      ...(edge.label && !spoken ? { label: edge.label } : {}),
      ...(spoken ? { markerEnd: arrow(back) } : {}),
    }
  }
  if (edge.lane) {
    // The vertical flow: cards are nodes, so a line only needs the right handles for its lane.
    const isCard = (id: string) => id.startsWith('said:')
    const sourceHandle = edge.lane === 'down' ? 's-bottom' : isCard(edge.source) ? `s-${edge.lane}` : edge.lane === 'left' ? 'back' : 'out'
    const targetHandle = edge.lane === 'down' ? 't-top' : isCard(edge.target) ? `t-${edge.lane}` : edge.lane === 'left' ? 'in' : 'return'
    return {
      id: edge.id, source: edge.source, target: edge.target, sourceHandle, targetHandle, type: 'smoothstep', pathOptions: { borderRadius: 12, offset: 28 }, animated: spoken, className,
      ...(spoken ? { markerEnd: arrow(back) } : {}),
    }
  }
  const base = {
    id: edge.id, source: edge.source, target: edge.target,
    sourceHandle: back ? 'back' : 'out', targetHandle: back ? 'return' : 'in',
    animated: spoken, className,
  }
  if (!spoken) return { ...base, label: edge.label || undefined, type: 'smoothstep', pathOptions: { borderRadius: 10 } }
  // What was said rides on the line as a card; the call and its count sit under it.
  return {
    ...base, type: 'said', data: { said: edge.said, caption: edge.caption ?? edge.label, kind: edge.kind, running: !!edge.running },
    markerEnd: arrow(back),
  }
}
