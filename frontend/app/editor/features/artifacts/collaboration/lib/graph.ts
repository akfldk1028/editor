import { AGENTS, type AgentSpec, USER } from '@/lib/agents'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { describeMessage } from './describe'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export type LiveState = 'up' | 'down' | 'unknown'

export interface GraphNode {
  id: string
  label: string
  /** The last thing this participant said or was asked, in the user's words; what it answers when it did not take part. */
  sub: string
  hub: boolean
  selected: boolean
  /** In the catalog but not in this run's record. */
  idle: boolean
  /** Whether the agent's service answers right now, when the status is known. */
  live: LiveState | null
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

export interface GraphOptions {
  /** The whole network to draw (default: every agent the conversation knows, the user aside). */
  catalog?: readonly Pick<AgentSpec, 'id' | 'tools'>[]
  live?: Readonly<Record<string, LiveState>>
}

export const NODE_WIDTH = 224
export const NODE_HEIGHT = 92
const COLUMNS = 3
const COLUMN_GAP = 48
const HUB_GAP = 120
const ROW_GAP = 28

const tools = (spec: Pick<AgentSpec, 'tools'> | undefined) => Object.keys(spec?.tools ?? {}).map((tool) => toolLabel(tool)).join(' · ')

/**
 * The whole network on the canvas the way the old flow showed it: the Orchestrator on the left, every agent
 * in a grid on the right — the ones this run spoke with first and bright, the rest dimmed — and one
 * right-angled edge per direction and pair, labelled with what and how many.
 */
export function buildGraph(messages: readonly CollaborationMessage[], selected?: string | null, options: GraphOptions = {}): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const catalog = options.catalog ?? AGENTS.filter((spec) => spec.id !== USER && spec.id !== ORCHESTRATOR)
  const spoken = [...new Set(messages.flatMap((message) => [message.from, message.to]))].filter((id) => id !== ORCHESTRATOR)
  const ids = [...spoken, ...catalog.map((spec) => spec.id).filter((id) => !spoken.includes(id))]
  if (!ids.length && !messages.length) return { nodes: [], edges: [] }
  const rows = Math.ceil(ids.length / COLUMNS)
  const gridHeight = rows * NODE_HEIGHT + Math.max(0, rows - 1) * ROW_GAP
  const requests = messages.filter((message) => message.direction === 'request').length
  const hub: GraphNode = {
    id: ORCHESTRATOR, label: agentLabel(ORCHESTRATOR), hub: true, selected: selected === ORCHESTRATOR, idle: false,
    live: options.live?.[ORCHESTRATOR] ?? null, sub: `요청 ${requests}건 · 응답 ${messages.length - requests}건`,
    position: { x: 0, y: Math.max(0, (gridHeight - NODE_HEIGHT) / 2) },
  }
  const nodes: GraphNode[] = [hub, ...ids.map((id, index) => {
    const last = [...messages].reverse().find((message) => message.from === id || message.to === id)
    const idle = !spoken.includes(id)
    return {
      id, label: agentLabel(id), hub: false, selected: selected === id, idle, live: options.live?.[id] ?? null,
      sub: last ? describeMessage(last).headline.replace(/^.*? · /, '') : tools(catalog.find((spec) => spec.id === id)),
      position: {
        x: NODE_WIDTH + HUB_GAP + (index % COLUMNS) * (NODE_WIDTH + COLUMN_GAP),
        y: Math.floor(index / COLUMNS) * (NODE_HEIGHT + ROW_GAP),
      },
    }
  })]
  const groups = new Map<string, CollaborationMessage[]>()
  for (const message of messages) {
    const key = `${message.from}→${message.to}`
    groups.set(key, [...(groups.get(key) ?? []), message])
  }
  const edges: GraphEdge[] = [...groups.entries()].map(([key, rows]) => {
    const first = rows[0]!
    const toolsUsed = [...new Set(rows.map((row) => row.tool))]
    const known = rows.every((row) => row.transport === 'a2a')
    const what = first.direction === 'request' ? `${toolsUsed.length === 1 ? `${toolLabel(toolsUsed[0])} ` : ''}요청` : '응답'
    return {
      id: key, source: first.from, target: first.to, kind: first.direction, known, count: rows.length,
      label: `${what} ${rows.length}건${known ? '' : ' · 전송 미확인'}`,
    }
  })
  return { nodes, edges }
}
