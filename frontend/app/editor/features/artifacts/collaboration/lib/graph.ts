import { USER } from '@/lib/agents'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { type CatalogEntry, type LiveState, mergeCatalog } from './catalog'
import { describeMessage } from './describe'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export type { LiveState } from './catalog'
export type Side = 'left' | 'right' | 'top' | 'bottom'

/** What the canvas needs of a catalog entry; a test may pass only an id. */
export type CatalogLike = Pick<CatalogEntry, 'id'> & Partial<Pick<CatalogEntry, 'label' | 'tools' | 'live'>>

export interface GraphNode {
  id: string
  label: string
  /** The last thing this participant said or was asked, in the user's words; what it answers when it did not take part. */
  sub: string
  kind: 'user' | 'hub' | 'agent'
  /** 1, 2, 3 … in the order the Orchestrator called it; null when it was not called. */
  order: number | null
  selected: boolean
  /** In the catalog but not in this run's record. */
  idle: boolean
  /** Whether the agent's service answers right now, when the status is known. */
  live: LiveState | null
  position: { x: number; y: number }
  /** Which side of the hub this node sits on, so edges leave the hub on that side. */
  side: Side
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  /** `user`: the person's request to the hub; `next`: the order the hub went on to the next agent; the rest is what was said. */
  kind: 'user' | 'next' | 'request' | 'response'
  label: string
  /** Every message on this edge was recorded over A2A (always true for user/next edges). */
  known: boolean
  count: number
}

export interface GraphOptions {
  /** The whole network to draw (default: every agent the conversation's folders know; the live catalog adds the rest). */
  catalog?: readonly CatalogLike[]
  /** Live states by id; an entry's own `live` is the fallback. */
  live?: Readonly<Record<string, LiveState>>
}

export const NODE_WIDTH = 176
export const NODE_HEIGHT = 84
const GAP_X = 120
const USER_GAP = 260
/** The agents the run did not call wait in rows under the flow. */
const IDLE_TOP = NODE_HEIGHT + 150
const IDLE_COLUMNS = 6
const IDLE_GAP_X = 24
const IDLE_GAP_Y = 24

const tools = (entry: CatalogLike | undefined) => Object.values(entry?.tools ?? {}).join(' · ')

/** The agents in the order the Orchestrator first spoke to them. */
export const callOrder = (messages: readonly CollaborationMessage[]): string[] =>
  [...new Set(messages.map((message) => (message.direction === 'request' ? message.to : message.from)))].filter((id) => id !== ORCHESTRATOR)

/**
 * The flow as it actually ran: the person → the Orchestrator → the agents it called, left to right in the order
 * it called them (numbered, with labelled request/answer edges), and under that every other agent of the
 * network, dimmed, with what it answers — so the whole team is on the canvas and the run's path reads at once.
 */
export function buildGraph(messages: readonly CollaborationMessage[], selected?: string | null, options: GraphOptions = {}): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const catalog: readonly CatalogLike[] = options.catalog ?? mergeCatalog()
  const entry = (id: string) => catalog.find((candidate) => candidate.id === id)
  const name = (id: string) => entry(id)?.label ?? agentLabel(id)
  const liveOf = (id: string) => options.live?.[id] ?? entry(id)?.live ?? null
  const called = callOrder(messages)
  const rest = catalog.map((candidate) => candidate.id).filter((id) => !called.includes(id))
  if (!called.length && !rest.length) return { nodes: [], edges: [] }
  const requests = messages.filter((message) => message.direction === 'request').length
  const names = Object.fromEntries(catalog.filter((candidate) => candidate.label).map((candidate) => [candidate.id, candidate.label!]))

  const user: GraphNode = { id: USER, label: agentLabel(USER), sub: '요청을 내고 답을 받습니다', kind: 'user', order: null, selected: selected === USER, idle: false, live: null, position: { x: -USER_GAP, y: 0 }, side: 'left' }
  const hub: GraphNode = {
    id: ORCHESTRATOR, label: agentLabel(ORCHESTRATOR), kind: 'hub', order: null, selected: selected === ORCHESTRATOR, idle: false,
    live: liveOf(ORCHESTRATOR), sub: `요청 ${requests}건 · 응답 ${messages.length - requests}건`, position: { x: 0, y: 0 }, side: 'right',
  }
  const spoken: GraphNode[] = called.map((id, index) => {
    const last = [...messages].reverse().find((message) => message.from === id || message.to === id)
    return {
      id, label: name(id), kind: 'agent', order: index + 1, selected: selected === id, idle: false, live: liveOf(id),
      sub: last ? describeMessage(last, names).headline.replace(/^.*? · /, '') : '',
      position: { x: (index + 1) * (NODE_WIDTH + GAP_X), y: 0 }, side: 'right',
    }
  })
  const waiting: GraphNode[] = rest.map((id, index) => ({
    id, label: name(id), kind: 'agent', order: null, selected: selected === id, idle: true, live: liveOf(id),
    sub: tools(entry(id)),
    position: { x: -USER_GAP + (index % IDLE_COLUMNS) * (NODE_WIDTH + IDLE_GAP_X), y: IDLE_TOP + Math.floor(index / IDLE_COLUMNS) * (NODE_HEIGHT + IDLE_GAP_Y) },
    side: 'bottom',
  }))

  const edges: GraphEdge[] = [{ id: 'user→orchestrator', source: USER, target: ORCHESTRATOR, kind: 'user', label: '', known: true, count: 0 }]
  for (let index = 1; index < called.length; index++) {
    edges.push({ id: `next:${called[index - 1]}→${called[index]}`, source: called[index - 1]!, target: called[index]!, kind: 'next', label: `${index + 1}번째`, known: true, count: 0 })
  }
  const groups = new Map<string, CollaborationMessage[]>()
  for (const message of messages) {
    const key = `${message.from}→${message.to}`
    groups.set(key, [...(groups.get(key) ?? []), message])
  }
  for (const [key, rows] of groups) {
    const first = rows[0]!
    const toolsUsed = [...new Set(rows.map((row) => row.tool))]
    const known = rows.every((row) => row.transport === 'a2a')
    const what = first.direction === 'request' ? `${toolsUsed.length === 1 ? `${toolLabel(toolsUsed[0])} ` : ''}요청` : '응답'
    edges.push({ id: key, source: first.from, target: first.to, kind: first.direction, known, count: rows.length, label: `${what} ${rows.length}건${known ? '' : ' · 전송 미확인'}` })
  }
  return { nodes: [user, hub, ...spoken, ...waiting], edges }
}
