import { USER } from '@/lib/agents'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { type CatalogEntry, type LiveState, mergeCatalog } from './catalog'
import { describeMessage } from './describe'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export type { LiveState } from './catalog'

/** What the canvas needs of a catalog entry; a test may pass only an id. */
export type CatalogLike = Pick<CatalogEntry, 'id'> & Partial<Pick<CatalogEntry, 'label' | 'tools' | 'live'>>

export interface GraphNode {
  id: string
  label: string
  /** The last thing this participant said or was asked, in the user's words; what it answers when it did not take part. */
  sub: string
  kind: 'user' | 'hub' | 'agent' | 'said'
  /** A `said` card (the vertical flow): what was said on one line, and under it which call and how many times. */
  said?: { text: string; caption: string; kind: 'request' | 'response'; running: boolean }
  /** 1, 2, 3 … in the order the Orchestrator called it; null when it was not called. */
  order: number | null
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
  /** `user`: the person's request to the hub; `next`: the order the hub went on to the next agent; the rest is what was said. */
  kind: 'user' | 'next' | 'request' | 'response'
  label: string
  /** What was last said on this edge, in the user's words (empty for user/next edges). */
  said: string
  /** The card's small line: who asked whom for what, or whose answer — `사용자 → Orchestrator Agent · 질문`, `Law Agent의 답`. */
  caption?: string
  /** Every message on this edge was recorded over A2A (always true for user/next edges). */
  known: boolean
  count: number
  /** The latest message on this edge is still running (the conversation is waiting on it). */
  running?: boolean
  /** The vertical flow: which way the line leaves and enters (`down` between stacked cards, `left`/`right` along the side lanes). */
  lane?: 'down' | 'left' | 'right'
}

export interface GraphOptions {
  /** The whole network to draw (default: every agent the conversation's folders know; the live catalog adds the rest). */
  catalog?: readonly CatalogLike[]
  /** Live states by id; an entry's own `live` is the fallback. */
  live?: Readonly<Record<string, LiveState>>
  /** `vertical` for a narrow canvas: one column — person, what they said, the Orchestrator, each call's card, the agent, its answer's card. */
  orientation?: 'horizontal' | 'vertical'
}

export const NODE_WIDTH = 176
export const NODE_HEIGHT = 84
/** Room between cards for what was said to ride on the lines (a card is up to 230 px wide). */
export const GAP_X = 300
const USER_GAP = NODE_WIDTH + GAP_X
/** The agents the run did not call wait in rows under the flow, below the answer cards. */
const IDLE_TOP = NODE_HEIGHT + 200
const IDLE_COLUMNS = 6
const IDLE_GAP_X = 24
const IDLE_GAP_Y = 24
/** The vertical flow's cards for what was said, and the room between the stacked items. */
export const CARD_WIDTH = 230
export const CARD_HEIGHT = 64
const V_GAP = 26
const V_IDLE_COLUMNS = 2

const tools = (entry: CatalogLike | undefined) => Object.values(entry?.tools ?? {}).join(' · ')
const GIST_CHARS = 110
/** The editor's own doors, recorded as the tool of the person's line: their label is the whole caption (`질문`, not `질문 요청`). */
const DOORS = new Set(['ask', 'conversation', 'law-analysis'])

/** The small line under what was said: who asked whom for what, or whose answer, and how many times when more than once. */
function captionOf(rows: readonly CollaborationMessage[], names: Readonly<Record<string, string>>, running: boolean): string {
  const first = rows[0]!
  const label = (id: string) => names[id] ?? agentLabel(id)
  const count = rows.length > 1 ? ` · ${rows.length}건` : ''
  if (first.direction === 'response') return `${label(first.from)}의 답${count}`
  const toolsUsed = [...new Set(rows.map((row) => row.tool).filter(Boolean))]
  const what = toolsUsed.length === 1 ? (DOORS.has(toolsUsed[0]!) ? toolLabel(toolsUsed[0]) : `${toolLabel(toolsUsed[0])} 요청`) : '요청'
  return `${label(first.from)} → ${label(first.to)} · ${what}${count}${running ? ' · 답을 기다리는 중' : ''}`
}

/** One message in the user's words, short enough for a card on the canvas: its first described line (never the record note). */
export function gist(message: CollaborationMessage, names: Readonly<Record<string, string>> = {}): string {
  const line = describeMessage(message, names).lines.find((candidate) => candidate && !/기록 원문|기록이 잘렸/.test(candidate)) ?? ''
  const flat = line.replace(/\s+/g, ' ').trim()
  return flat.length > GIST_CHARS ? `${flat.slice(0, GIST_CHARS - 1)}…` : flat
}

/** The agents in the order the Orchestrator first spoke to them. */
export const callOrder = (messages: readonly CollaborationMessage[]): string[] =>
  [...new Set(messages.map((message) => (message.direction === 'request' ? message.to : message.from)))].filter((id) => id !== ORCHESTRATOR && id !== USER)

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

  const lastBy = (id: string) => [...messages].reverse().find((message) => message.from === id)
  const userSaid = lastBy(USER)
  const hubSaid = [...messages].reverse().find((message) => message.from === ORCHESTRATOR && message.to === USER)
  const user: GraphNode = { id: USER, label: agentLabel(USER), sub: userSaid ? gist(userSaid, names) : '요청을 내고 답을 받습니다', kind: 'user', order: null, selected: selected === USER, idle: false, live: null, position: { x: -USER_GAP, y: 0 } }
  const hub: GraphNode = {
    id: ORCHESTRATOR, label: agentLabel(ORCHESTRATOR), kind: 'hub', order: null, selected: selected === ORCHESTRATOR, idle: false,
    live: liveOf(ORCHESTRATOR), sub: (hubSaid && gist(hubSaid, names)) || `요청 ${requests}건 · 응답 ${messages.length - requests}건`, position: { x: 0, y: 0 },
  }
  const spoken: GraphNode[] = called.map((id, index) => {
    const last = [...messages].reverse().find((message) => message.from === id || message.to === id)
    return {
      id, label: name(id), kind: 'agent', order: index + 1, selected: selected === id, idle: false, live: liveOf(id),
      sub: last ? gist(last, names) || describeMessage(last, names).headline.replace(/^.*? · /, '') : '',
      position: { x: (index + 1) * (NODE_WIDTH + GAP_X), y: 0 },
    }
  })
  const waiting: GraphNode[] = rest.map((id, index) => ({
    id, label: name(id), kind: 'agent', order: null, selected: selected === id, idle: true, live: liveOf(id),
    sub: tools(entry(id)),
    position: { x: -USER_GAP + (index % IDLE_COLUMNS) * (NODE_WIDTH + IDLE_GAP_X), y: IDLE_TOP + Math.floor(index / IDLE_COLUMNS) * (NODE_HEIGHT + IDLE_GAP_Y) },
  }))

  const edges: GraphEdge[] = []
  for (let index = 1; index < called.length; index++) {
    edges.push({ id: `next:${called[index - 1]}→${called[index]}`, source: called[index - 1]!, target: called[index]!, kind: 'next', label: `${index + 1}번째`, said: '', known: true, count: 0 })
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
    const latest = rows[rows.length - 1]!
    const running = latest.state === 'running'
    edges.push({ id: key, source: first.from, target: first.to, kind: first.direction, known, count: rows.length, label: `${what} ${rows.length}건${known ? '' : ' · 전송 미확인'}`, said: gist(latest, names), caption: captionOf(rows, names, running), running })
  }
  // The person's standing line to the hub is drawn only until the person has actually said something on the record.
  if (!groups.has(`${USER}→${ORCHESTRATOR}`)) edges.unshift({ id: `person:${USER}→${ORCHESTRATOR}`, source: USER, target: ORCHESTRATOR, kind: 'user', label: '', said: '', known: true, count: 0 })
  if (options.orientation === 'vertical') return vertical(user, hub, spoken, waiting, edges)
  return { nodes: [user, hub, ...spoken, ...waiting], edges }
}

/**
 * The same flow as one column for a narrow canvas: the person, what they said, the Orchestrator, then for each agent it
 * called the request card, the agent and its answer card; the Orchestrator's reply to the person last. Requests leave on
 * the left lane and answers return on the right lane, so no line crosses a card. The waiting agents sit under it in pairs.
 */
function vertical(user: GraphNode, hub: GraphNode, spoken: GraphNode[], waiting: GraphNode[], edges: GraphEdge[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const spokenEdges = edges.filter((edge) => edge.kind === 'request' || edge.kind === 'response')
  const between = (from: string, to: string) => spokenEdges.find((edge) => edge.source === from && edge.target === to)
  const nodes: GraphNode[] = []
  const out: GraphEdge[] = []
  let y = 0
  const place = (node: GraphNode) => { nodes.push({ ...node, position: { x: 0, y } }); y += NODE_HEIGHT + V_GAP }
  const card = (edge: GraphEdge): string => {
    const id = `said:${edge.id}`
    nodes.push({
      id, label: '', sub: '', kind: 'said', order: null, selected: false, idle: false, live: null, position: { x: (NODE_WIDTH - CARD_WIDTH) / 2, y },
      said: { text: edge.said, caption: edge.caption ?? edge.label, kind: edge.kind as 'request' | 'response', running: !!edge.running },
    })
    y += CARD_HEIGHT + V_GAP
    return id
  }
  const line = (edge: GraphEdge, source: string, target: string, lane: 'down' | 'left' | 'right') =>
    out.push({ ...edge, id: `${edge.id}:${source}→${target}`, source, target, lane })

  place(user)
  const asked = between(USER, ORCHESTRATOR)
  if (asked) {
    const id = card(asked)
    line(asked, USER, id, 'down')
    line(asked, id, ORCHESTRATOR, 'down')
  } else {
    const person = edges.find((edge) => edge.kind === 'user')
    if (person) out.push({ ...person, lane: 'down' })
  }
  place(hub)
  for (const agent of spoken) {
    const request = between(ORCHESTRATOR, agent.id)
    if (request) {
      const id = card(request)
      line(request, ORCHESTRATOR, id, 'left')
      line(request, id, agent.id, 'down')
    }
    place(agent)
    const answer = between(agent.id, ORCHESTRATOR)
    if (answer) {
      const id = card(answer)
      line(answer, agent.id, id, 'down')
      line(answer, id, ORCHESTRATOR, 'right')
    }
  }
  const replied = between(ORCHESTRATOR, USER)
  if (replied) {
    const id = card(replied)
    line(replied, ORCHESTRATOR, id, 'right')
    line(replied, id, USER, 'left')
  }
  const idleTop = y + 30
  const idle = waiting.map((node, index) => ({
    ...node,
    position: { x: (index % V_IDLE_COLUMNS) * (NODE_WIDTH + IDLE_GAP_X) - (NODE_WIDTH + IDLE_GAP_X) / 2, y: idleTop + Math.floor(index / V_IDLE_COLUMNS) * (NODE_HEIGHT + IDLE_GAP_Y) },
  }))
  return { nodes: [...nodes, ...idle], edges: out }
}
