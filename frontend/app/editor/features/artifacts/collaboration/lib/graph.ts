import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { describeMessage } from './describe'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export interface GraphNode {
  id: string
  label: string
  /** The last thing this participant said or was asked, in the user's words. */
  sub: string
  hub: boolean
  selected: boolean
  position: { x: number; y: number }
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  kind: 'request' | 'response'
  label: string
  /** Every message on this edge was recorded over A2A. */
  known: boolean
  count: number
}

export const NODE_WIDTH = 224
export const NODE_HEIGHT = 92
const COLUMN_GAP = 160
const ROW_GAP = 36

/** The Orchestrator on the left, the agents it spoke with stacked on the right; one edge per direction and pair. */
export function buildGraph(messages: readonly CollaborationMessage[], selected?: string | null): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const ids = [...new Set(messages.flatMap((message) => [message.from, message.to]))]
  if (!ids.length) return { nodes: [], edges: [] }
  const peers = ids.filter((id) => id !== ORCHESTRATOR)
  const column = peers.length ? peers.length * NODE_HEIGHT + (peers.length - 1) * ROW_GAP : NODE_HEIGHT
  const nodes: GraphNode[] = ids.map((id) => {
    const index = peers.indexOf(id)
    const last = [...messages].reverse().find((message) => message.from === id || message.to === id)
    const requests = messages.filter((message) => message.direction === 'request').length
    return {
      id, label: agentLabel(id), hub: id === ORCHESTRATOR, selected: selected === id,
      // The hub counts what it sent and got back; an agent shows its last exchange.
      sub: id === ORCHESTRATOR ? `요청 ${requests}건 · 응답 ${messages.length - requests}건` : last ? describeMessage(last).headline.replace(/^.*? · /, '') : '',
      position: id === ORCHESTRATOR
        ? { x: 0, y: (column - NODE_HEIGHT) / 2 }
        : { x: NODE_WIDTH + COLUMN_GAP, y: index * (NODE_HEIGHT + ROW_GAP) },
    }
  })
  const groups = new Map<string, CollaborationMessage[]>()
  for (const message of messages) {
    const key = `${message.from}→${message.to}`
    groups.set(key, [...(groups.get(key) ?? []), message])
  }
  const edges: GraphEdge[] = [...groups.entries()].map(([key, rows]) => {
    const first = rows[0]!
    const tools = [...new Set(rows.map((row) => row.tool))]
    const known = rows.every((row) => row.transport === 'a2a')
    const what = first.direction === 'request' ? `${tools.length === 1 ? `${toolLabel(tools[0])} ` : ''}요청` : '응답'
    return {
      id: key, source: first.from, target: first.to, kind: first.direction, known, count: rows.length,
      label: `${what} ${rows.length}건${known ? '' : ' · 전송 미확인'}`,
    }
  })
  return { nodes, edges }
}
