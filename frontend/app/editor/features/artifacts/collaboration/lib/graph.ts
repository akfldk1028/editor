import { USER } from '@/lib/agents'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { type CatalogEntry, type LiveState, mergeCatalog } from './catalog'
import { describeMessage } from './describe'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export type { LiveState } from './catalog'

/** What the canvas needs of a catalog entry; a test may pass only an id. */
export type CatalogLike = Pick<CatalogEntry, 'id'> & Partial<Pick<CatalogEntry, 'label' | 'tools' | 'live'>>

/** One message on a card, in the user's words: which call it was, the gist the closed card shows, all of it for the opened one. */
export interface SaidItem {
  id: string
  caption: string
  text: string
  full: string
  /** The message as it was recorded: an opened card shows it under the words. */
  raw: string
  /** The ledger list cut `raw`; an opened card reads the whole call by the item's id. */
  clipped: boolean
  running: boolean
}

export interface GraphNode {
  id: string
  /** The participant this node stands for when its id is not one (a step card in the pattern view). */
  agent?: string
  /** Where a step stands (완료 · 진행 중 · 근거 필요 …), shown on the card's header next to the name. */
  status?: string
  label: string
  /** The last thing this participant said or was asked, in the user's words; what it answers when it did not take part. */
  sub: string
  kind: 'user' | 'hub' | 'agent' | 'said'
  /** Everything this participant sent or was sent, in call order, to step through on its card; empty when it did not take part. */
  items: SaidItem[]
  /** A `said` card: every message on one line in call order (stepped through with ‹ ›), how the line is drawn. */
  said?: { items: SaidItem[]; kind: 'request' | 'response'; running: boolean; known: boolean; party: string }
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
  /** Every message on this edge in call order, for its card. */
  items?: SaidItem[]
  /** Every message on this edge was recorded over A2A (always true for user/next edges). */
  known: boolean
  count: number
  /** The latest message on this edge is still running (the conversation is waiting on it). */
  running?: boolean
  /** The vertical flow: which way the line leaves and enters (`down` between stacked cards, `left`/`right` along the side lanes). */
  lane?: 'down' | 'left' | 'right'
  /** The wide flow: the exact handles the line leaves and enters by. */
  sourceHandle?: string
  targetHandle?: string
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
export const NODE_HEIGHT = 124
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
export const CARD_HEIGHT = 92
const V_GAP = 26
const V_IDLE_COLUMNS = 2
/** The wide flow: room for one card (a one-line caption, two lines of text, the ‹ › / 전체 보기 row), between an agent's rows, and between columns. */
export const SLOT = 104
const ROW_GAP = 28
const COL_GAP = 56

const tools = (entry: CatalogLike | undefined) => Object.values(entry?.tools ?? {}).join(' · ')
const GIST_CHARS = 110
/** The whole message in the user's words: plain text as written; a record as all its described lines. */
export function fullText(message: CollaborationMessage, names: Readonly<Record<string, string>> = {}): string {
  // Plain text as written; a record — whole or cut — as its described lines, never raw JSON.
  if (!/^\s*[[{]/.test(message.text)) return message.text.trim()
  return describeMessage(message, names).lines.filter((line) => line && !/기록 원문/.test(line)).join('\n')
}

/**
 * Each call's place in the conversation (1, 2, 3 … in the order the calls were made) by message id, an answer
 * carrying its request's number; the person's own messages are not calls. `startedAt` times each numbered call.
 */
export interface CallOrder { number: Map<string, number>; startedAt: Map<number, number> }

export function callNumbers(messages: readonly CollaborationMessage[]): CallOrder {
  const number = new Map<string, number>()
  const startedAt = new Map<number, number>()
  const requests = messages.map((message, index) => ({ message, index }))
    .filter(({ message }) => message.direction === 'request' && message.from !== USER)
    .sort((a, b) => (a.message.at ?? 0) - (b.message.at ?? 0) || a.index - b.index)
  requests.forEach(({ message }, index) => {
    number.set(message.id, index + 1)
    if (message.at) startedAt.set(index + 1, message.at)
  })
  // An answer carries its request's number: the ledger's ids pair them (`hop:7:request` ↔ `hop:7:response`).
  for (const message of messages) {
    const asked = message.direction === 'response' ? number.get(message.id.replace(/:response$/, ':request')) : undefined
    if (asked) number.set(message.id, asked)
  }
  return { number, startedAt }
}

/** The numbers a card stands for, short: " · 2·3·5번째", " · 2·3·5·6·8 …번째" past five. */
function numbersLabel(rows: readonly CollaborationMessage[], order: CallOrder): string {
  const numbers = [...new Set(rows.map((row) => order.number.get(row.id)).filter((n): n is number => !!n))].sort((a, b) => a - b)
  if (!numbers.length) return ''
  return ` · ${numbers.slice(0, 5).join('·')}${numbers.length > 5 ? ' …' : ''}번째`
}

/** A tool in words; one no folder names reads as a lookup, never as its id. */
function toolWords(tool: string | null | undefined): string {
  const label = toolLabel(tool)
  return label !== tool && label !== '—' ? label : '조회'
}

/** Messages in the order their calls were made (an answer next to its request's number). */
function inCallOrder(rows: readonly CollaborationMessage[], order: CallOrder): CollaborationMessage[] {
  return [...rows].sort((a, b) => (order.number.get(a.id) ?? 0) - (order.number.get(b.id) ?? 0) || (a.at ?? 0) - (b.at ?? 0))
}

/** One message as a card item: who asked whom for what (or whose answer), its call number and how long it took. */
function itemOf(message: CollaborationMessage, names: Readonly<Record<string, string>>, order: CallOrder): SaidItem {
  const label = (id: string) => names[id] ?? agentLabel(id)
  const n = order.number.get(message.id)
  const numbered = n ? ` · ${n}번째` : ''
  const running = message.state === 'running'
  const started = n ? order.startedAt.get(n) : undefined
  const took = message.direction === 'response' && started && message.at ? ` · ${Math.max(0, Math.round((message.at - started) / 1000))}초` : ''
  const what = message.tool && DOORS.has(message.tool) ? toolLabel(message.tool) : `${toolWords(message.tool)} 요청`
  const caption = message.direction === 'response'
    ? `${label(message.from)}의 답${numbered}${took}`
    : `${label(message.from)} → ${label(message.to)} · ${what}${numbered}${running ? ' · 답을 기다리는 중' : ''}`
  const text = gist(message, names)
  return { id: message.id, caption, text, full: fullText(message, names) || text, raw: message.text, clipped: message.truncated && message.id.startsWith('hop:'), running }
}

export const itemsOf = (rows: readonly CollaborationMessage[], names: Readonly<Record<string, string>>, order: CallOrder): SaidItem[] =>
  inCallOrder(rows, order).map((row) => itemOf(row, names, order))

/** The editor's own doors, recorded as the tool of the person's line: their label is the whole caption (`질문`, not `질문 요청`). */
const DOORS = new Set(['ask', 'conversation', 'law-analysis'])

/** The small line under what was said: who asked whom for what, or whose answer, and how many times when more than once. */
function captionOf(rows: readonly CollaborationMessage[], names: Readonly<Record<string, string>>, running: boolean, order: CallOrder): string {
  const first = rows[0]!
  const label = (id: string) => names[id] ?? agentLabel(id)
  const count = rows.length > 1 ? ` · ${rows.length}건` : ''
  const numbers = numbersLabel(rows, order)
  if (first.direction === 'response') return `${label(first.from)}의 답${count}${numbers}`
  const toolsUsed = [...new Set(rows.map((row) => row.tool).filter(Boolean))]
  const what = toolsUsed.length === 1 ? (DOORS.has(toolsUsed[0]!) ? toolLabel(toolsUsed[0]) : `${toolLabel(toolsUsed[0])} 요청`) : '요청'
  return `${label(first.from)} → ${label(first.to)} · ${what}${count}${numbers}${running ? ' · 답을 기다리는 중' : ''}`
}

/** One message in the user's words, short enough for a card on the canvas: its first described line (never the record note). */
export function gist(message: CollaborationMessage, names: Readonly<Record<string, string>> = {}): string {
  const line = describeMessage(message, names).lines.find((candidate) => candidate && !/기록 원문|기록이 잘렸/.test(candidate)) ?? ''
  const flat = line.replace(/\s+/g, ' ').trim()
  return flat.length > GIST_CHARS ? `${flat.slice(0, GIST_CHARS - 1)}…` : flat
}

/** The lookups every agent answers for the Orchestrator's conversation engine: not steps of the work. */
const isLookup = (tool: string) => tool.endsWith('_tool_catalog') || tool.endsWith('_conversation_contract')

/**
 * How the Orchestrator's calls actually ran, as waves: calls whose time spans overlap ran at the same time (one wave),
 * a call that began after the wave's last answer starts the next. The ledger times every call (request `at` = start,
 * its answer's `at` = end); a call still without an answer runs to now. Lookups (catalogs, contracts) are left out.
 */
export function callWaves(messages: readonly CollaborationMessage[], now = Date.now()): { id: string; to: string; tool: string; state: string }[][] {
  const ends = new Map<string, number>()
  for (const message of messages) {
    if (message.direction === 'response' && message.at) ends.set(message.id.replace(/:response$/, ':request'), message.at)
  }
  const calls = messages
    .filter((message) => message.direction === 'request' && message.from !== USER && message.at && !isLookup(message.tool))
    .sort((a, b) => (a.at ?? 0) - (b.at ?? 0))
  const waves: { id: string; to: string; tool: string; state: string }[][] = []
  let until = -1
  for (const call of calls) {
    const start = call.at ?? 0
    const end = ends.get(call.id) ?? now
    if (!waves.length || start >= until) { waves.push([]); until = end } else until = Math.max(until, end)
    waves[waves.length - 1]!.push({ id: call.id, to: call.to, tool: call.tool, state: ends.has(call.id) ? call.state : 'running' })
  }
  return waves
}

/** The waves in the user's words: "대지 주변 현황 ‖ 용도지역 → 법규 분석 → 대지 사실 확인" (same-time calls joined with ‖). */
export const wavesLabel = (waves: readonly { to: string; tool: string }[][]): string =>
  waves.map((wave) => {
    const names = wave.map((call) => toolLabel(call.tool))
    return names.length > 1 ? `[${names.join(' ‖ ')}]` : names[0]!
  }).join(' → ')

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
  const order = callNumbers(messages)
  const involving = (id: string) => itemsOf(messages.filter((message) => message.from === id || message.to === id), names, order)
  const user: GraphNode = { id: USER, label: agentLabel(USER), sub: userSaid ? gist(userSaid, names) : '요청을 내고 답을 받습니다', kind: 'user', items: involving(USER), order: null, selected: selected === USER, idle: false, live: null, position: { x: -USER_GAP, y: 0 } }
  const hub: GraphNode = {
    id: ORCHESTRATOR, label: agentLabel(ORCHESTRATOR), kind: 'hub', items: involving(ORCHESTRATOR), order: null, selected: selected === ORCHESTRATOR, idle: false,
    live: liveOf(ORCHESTRATOR), sub: (hubSaid && gist(hubSaid, names)) || `요청 ${requests}건 · 응답 ${messages.length - requests}건`, position: { x: 0, y: 0 },
  }
  const spoken: GraphNode[] = called.map((id, index) => {
    const last = [...messages].reverse().find((message) => message.from === id || message.to === id)
    return {
      id, label: name(id), kind: 'agent', items: involving(id), order: index + 1, selected: selected === id, idle: false, live: liveOf(id),
      sub: last ? gist(last, names) || describeMessage(last, names).headline.replace(/^.*? · /, '') : '',
      position: { x: (index + 1) * (NODE_WIDTH + GAP_X), y: 0 },
    }
  })
  const waiting: GraphNode[] = rest.map((id, index) => ({
    id, label: name(id), kind: 'agent', items: [], order: null, selected: selected === id, idle: true, live: liveOf(id),
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
    edges.push({ id: key, source: first.from, target: first.to, kind: first.direction, known, count: rows.length, label: `${what} ${rows.length}건${known ? '' : ' · 전송 미확인'}`, said: gist(latest, names), items: itemsOf(rows, names, order), caption: captionOf(rows, names, running, order), running })
  }
  // An owner that answered the person was reached through the Orchestrator even when that call is not on the record yet:
  // the relay is drawn (dashed, unknown) so the path reads person → Orchestrator → owner, without inventing what was asked.
  for (const id of called) {
    if (!groups.has(`${id}→${USER}`) || groups.has(`${ORCHESTRATOR}→${id}`)) continue
    const note = '요청 내용은 Orchestrator가 아직 기록으로 남기지 않아요'
    edges.push({ id: `${ORCHESTRATOR}→${id}`, source: ORCHESTRATOR, target: id, kind: 'request', known: false, count: 0, label: '전달 · 요청 내용 미기록',
      said: note, items: [{ id: `relay:${id}`, caption: `${name(ORCHESTRATOR)} → ${name(id)} · 전달`, text: note, full: note, raw: '', clipped: false, running: false }],
      caption: `${name(ORCHESTRATOR)} → ${name(id)} · 전달`, running: false })
  }
  // The person's standing line to the hub is drawn only until the person has actually said something on the record.
  if (!groups.has(`${USER}→${ORCHESTRATOR}`)) edges.unshift({ id: `person:${USER}→${ORCHESTRATOR}`, source: USER, target: ORCHESTRATOR, kind: 'user', label: '', said: '', known: true, count: 0 })
  if (options.orientation === 'vertical') return vertical(user, hub, spoken, waiting, edges)
  return fanned(user, hub, spoken, waiting, edges)
}

/** Whom a line is about: the agent at its other end from the person and the Orchestrator, or the Orchestrator itself. */
export const partyOf = (source: string, target: string): string =>
  [source, target].find((id) => id !== ORCHESTRATOR && id !== USER) ?? ORCHESTRATOR

/** What was said on one line, as a card of its own at (x, y). */
function saidCard(edge: GraphEdge, x: number, y: number): GraphNode {
  return {
    id: `said:${edge.id}`, label: '', sub: '', kind: 'said', items: [], order: null, selected: false, idle: false, live: null, position: { x, y },
    said: { items: edge.items ?? [], kind: edge.kind as 'request' | 'response', running: !!edge.running, known: edge.known, party: partyOf(edge.source, edge.target) },
  }
}

/**
 * The flow for a wide canvas, fanned out from the Orchestrator: the person, with their question above and the reply below,
 * then one row per agent it called, in order: the request card over the answer card between the Orchestrator and the agent.
 * Every line runs to its own card, so no line crosses another agent and no card sits on another's line. The waiting agents sit below.
 */
function fanned(user: GraphNode, hub: GraphNode, spoken: GraphNode[], waiting: GraphNode[], edges: GraphEdge[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const spokenEdges = edges.filter((edge) => edge.kind === 'request' || edge.kind === 'response')
  const between = (from: string, to: string) => spokenEdges.find((edge) => edge.source === from && edge.target === to)
  const nodes: GraphNode[] = []
  const out: GraphEdge[] = []
  const card = (edge: GraphEdge, x: number, y: number) => {
    const node = saidCard(edge, x, y)
    nodes.push(node)
    return node.id
  }
  const line = (edge: GraphEdge, source: string, sourceHandle: string, target: string, targetHandle: string) =>
    out.push({ ...edge, id: `${edge.id}:${source}→${target}`, source, target, sourceHandle, targetHandle })

  const row = 2 * SLOT + ROW_GAP
  const span = spoken.length ? spoken.length * row - ROW_GAP : 2 * SLOT
  const middle = span / 2
  const leftCards = -(CARD_WIDTH + COL_GAP)
  const rightCards = NODE_WIDTH + COL_GAP
  const personX = leftCards - COL_GAP - NODE_WIDTH
  nodes.push({ ...user, position: { x: personX, y: middle - NODE_HEIGHT / 2 } }, { ...hub, position: { x: 0, y: middle - NODE_HEIGHT / 2 } })
  const asked = between(USER, ORCHESTRATOR)
  if (asked) {
    const id = card(asked, leftCards, middle - SLOT)
    line(asked, USER, 'out', id, 't-left')
    line(asked, id, 's-right', ORCHESTRATOR, 'in')
  } else {
    const person = edges.find((edge) => edge.kind === 'user')
    if (person) out.push({ ...person, sourceHandle: 'out', targetHandle: 'in' })
  }
  const replied = between(ORCHESTRATOR, USER)
  if (replied) {
    const id = card(replied, leftCards, middle + 8)
    line(replied, ORCHESTRATOR, 'back', id, 't-right')
    line(replied, id, 's-left', USER, 'return')
  }
  spoken.forEach((agent, index) => {
    const top = index * row
    nodes.push({ ...agent, position: { x: rightCards + CARD_WIDTH + COL_GAP, y: top + SLOT - NODE_HEIGHT / 2 } })
    const request = between(ORCHESTRATOR, agent.id)
    if (request) {
      const id = card(request, rightCards, top)
      line(request, ORCHESTRATOR, 'out', id, 't-left')
      line(request, id, 's-right', agent.id, 'in')
    }
    // Its answer to the Orchestrator, or (the conversation's owner reply) to the person directly.
    const answer = between(agent.id, ORCHESTRATOR) ?? between(agent.id, USER)
    if (answer) {
      const id = card(answer, rightCards, top + SLOT)
      line(answer, agent.id, 'back', id, 't-right')
      line(answer, id, 's-left', answer.target, 'return')
    }
  })
  const idleTop = span + 90
  const idle = waiting.map((node, index) => ({
    ...node,
    position: { x: personX + (index % IDLE_COLUMNS) * (NODE_WIDTH + IDLE_GAP_X), y: idleTop + Math.floor(index / IDLE_COLUMNS) * (NODE_HEIGHT + IDLE_GAP_Y) },
  }))
  return { nodes: [...nodes, ...idle], edges: out }
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
    const node = saidCard(edge, (NODE_WIDTH - CARD_WIDTH) / 2, y)
    nodes.push(node)
    y += CARD_HEIGHT + V_GAP
    return node.id
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
    // An owner that answered the person directly (the conversation's owner reply): its words go back to the person.
    const toPerson = between(agent.id, USER)
    if (toPerson) {
      const id = card(toPerson)
      line(toPerson, agent.id, id, 'down')
      line(toPerson, id, USER, 'left')
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
