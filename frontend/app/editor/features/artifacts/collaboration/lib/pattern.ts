/**
 * The pattern a turn ran, drawn as steps: a declared cooperation workflow's steps and dependencies, or — without
 * one — the Orchestrator's own calls as the ledger timed them (same-time calls in one column, columns in order).
 * Pure: the flow draws what this returns.
 */
import { USER } from '@/lib/agents'
import { phaseLabel, stepStatus, stepTitle, type Workflow } from '@/lib/design-conversation/workflow'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { callNumbers, callWaves, CARD_WIDTH, COL_GAP, gist, type GraphEdge, type GraphNode, itemsOf, NODE_HEIGHT, NODE_WIDTH, ROW_GAP, saidCard, SLOT } from './graph'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export interface PatternStep {
  id: string
  owner: string
  /** What the step does, in the user's words: the workflow step's own title or the tool's name. */
  title: string
  /** 조회 · 제안 · 검토 … for a declared workflow's step; none for a plain call. */
  phase?: string
  status: string
  code?: string
  /** 0 for the steps that start first; a step's column is one past the furthest column it waited for. */
  column: number
  /** What this step exchanged: its request and its answer, as recorded (empty when the record has none yet). */
  messages: CollaborationMessage[]
}
export interface PatternEdge { source: string; target: string; label?: string }
export interface Pattern { steps: PatternStep[]; edges: PatternEdge[]; declared: boolean }

/** The steps as they ran this turn: the declared workflow when there is one, else the calls' waves. */
export function patternOf(messages: readonly CollaborationMessage[], workflow?: Workflow | null, now = Date.now()): Pattern {
  // A call's record: its request and the answer the ledger paired with it (`hop:7:request` ↔ `hop:7:response`).
  const exchange = (requestId: string) => messages.filter((message) => message.id === requestId || message.id === requestId.replace(/:request$/, ':response'))
  if (workflow) {
    const columns = new Map<string, number>()
    const column = (id: string): number => {
      if (columns.has(id)) return columns.get(id)!
      const parents = workflow.edges.filter((edge) => edge.target === id)
      const value = parents.length ? Math.max(...parents.map((edge) => column(edge.source))) + 1 : 0
      columns.set(id, value)
      return value
    }
    // The workflow record does not name the ledger's calls: a step's call is the next request to its owner for its
    // tool not yet claimed by an earlier step (steps of one tool are matched in their recorded order).
    const claimed = new Set<string>()
    const requestFor = (owner: string, tool: string) => messages.find((message) => message.direction === 'request' && message.to === owner && message.tool === tool && message.at && !claimed.has(message.id))
    const steps = Object.entries(workflow.steps).map(([id, step]) => {
      const request = requestFor(step.owner, step.tool)
      if (request) claimed.add(request.id)
      return { id, owner: step.owner, title: stepTitle(step), phase: step.phase, status: step.status, code: step.code, column: column(id), messages: request ? exchange(request.id) : [] }
    })
    return { steps, edges: workflow.edges.map((edge) => ({ source: edge.source, target: edge.target })), declared: true }
  }
  const waves = callWaves(messages, now)
  const steps: PatternStep[] = waves.flatMap((wave, column) => wave.map((call, index) => ({ id: `call:${column}:${index}`, owner: call.to, title: toolLabel(call.tool), status: call.state, column, messages: exchange(call.id) })))
  // Every call of a wave began after the whole wave before it had answered: each earlier call leads to each later one.
  const edges: PatternEdge[] = waves.flatMap((wave, column) => (column ? wave.flatMap((_, index) => waves[column - 1]!.map((_, parent) => ({ source: `call:${column - 1}:${parent}`, target: `call:${column}:${index}` }))) : []))
  return { steps, edges, declared: false }
}

/** One column of the pattern: the request card over the answer card, then the step's card — as the 에이전트 view spaces them. */
export const PATTERN_COLUMN = CARD_WIDTH + COL_GAP + NODE_WIDTH + COL_GAP
export const PATTERN_ROW = 2 * SLOT + ROW_GAP

/**
 * The pattern on the canvas, in the 에이전트 view's own language: the person and the Orchestrator exactly as that view
 * draws them (their cards, what they said), then one column per wave of steps. Each step is its owner's card with
 * where it stands on the header, and — when the record has them — the orange request card and the green answer card
 * on its lines, stepped through like any card of the 에이전트 view: what came in from the step before, what went out.
 * Step nodes carry `agent` so a click picks the owner.
 */
export function patternGraph(pattern: Pattern, names: Readonly<Record<string, string>> = {}, from: readonly GraphNode[] = [], messages: readonly CollaborationMessage[] = []): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const name = (id: string) => names[id] ?? agentLabel(id)
  const order = callNumbers(messages)
  const base: Pick<GraphNode, 'items' | 'selected' | 'idle' | 'live' | 'order'> = { items: [], selected: false, idle: false, live: null, order: null }
  const given = (id: string) => from.find((node) => node.id === id)
  const user = given(USER) ?? { ...base, id: USER, label: agentLabel(USER), sub: '요청을 내고 답을 받습니다', kind: 'user' as const, position: { x: 0, y: 0 } }
  const hub = given(ORCHESTRATOR) ?? { ...base, id: ORCHESTRATOR, label: name(ORCHESTRATOR), sub: '', kind: 'hub' as const, position: { x: 0, y: 0 } }
  const hubX = NODE_WIDTH + COL_GAP
  const nodes: GraphNode[] = [
    { ...user, agent: USER, position: { x: 0, y: -NODE_HEIGHT / 2 } },
    { ...hub, agent: ORCHESTRATOR, position: { x: hubX, y: -NODE_HEIGHT / 2 } },
  ]
  const edges: GraphEdge[] = []
  const wide = { said: '', known: true } as const
  const line = (edge: GraphEdge, source: string, sourceHandle: string, target: string, targetHandle: string) =>
    edges.push({ ...edge, id: `${edge.id}:${source}→${target}`, source, target, sourceHandle, targetHandle })
  edges.push({ id: `person:${USER}→${ORCHESTRATOR}`, source: USER, target: ORCHESTRATOR, kind: 'user', label: '', count: 0, sourceHandle: 'out', targetHandle: 'in', ...wide })

  const byId = new Map(pattern.steps.map((step) => [step.id, step]))
  const parentsOf = (id: string) => pattern.edges.filter((edge) => edge.target === id).map((edge) => edge.source)
  // Where a step's lines start and end: its request card and its answer card when the record has them, else the step itself.
  const requestCard = new Map<string, string>()
  const answerCard = new Map<string, string>()
  const columns = Math.max(-1, ...pattern.steps.map((step) => step.column)) + 1
  for (let column = 0; column < columns; column += 1) {
    const wave = pattern.steps.filter((step) => step.column === column)
    const colX = hubX + NODE_WIDTH + COL_GAP + column * PATTERN_COLUMN
    wave.forEach((step, index) => {
      const centerY = (index - (wave.length - 1) / 2) * PATTERN_ROW
      const top = centerY - SLOT
      const state = stepStatus(step.status, step.code)
      nodes.push({ ...base, id: step.id, agent: step.owner, label: name(step.owner), status: state.label, sub: step.title, kind: 'agent', order: column + 1,
        items: itemsOf(step.messages, names, order), position: { x: colX + CARD_WIDTH + COL_GAP, y: centerY - NODE_HEIGHT / 2 } })
      const request = step.messages.find((message) => message.direction === 'request')
      const answer = step.messages.find((message) => message.direction === 'response')
      const running = step.status === 'running'
      if (request) {
        const edge: GraphEdge = { id: `${step.id}:request`, source: ORCHESTRATOR, target: step.id, kind: 'request', label: `${step.title} 요청`, count: 1, known: request.transport === 'a2a', said: gist(request, names), items: itemsOf([request], names, order), running }
        const card = saidCard(edge, colX, top)
        card.said!.party = step.owner
        nodes.push(card)
        requestCard.set(step.id, card.id)
        line(edge, card.id, 's-right', step.id, 'in')
      }
      if (answer) {
        const edge: GraphEdge = { id: `${step.id}:answer`, source: step.id, target: ORCHESTRATOR, kind: 'response', label: `${step.title} 응답`, count: 1, known: answer.transport === 'a2a', said: gist(answer, names), items: itemsOf([answer], names, order), running }
        const card = saidCard(edge, colX, top + SLOT)
        card.said!.party = step.owner
        nodes.push(card)
        answerCard.set(step.id, card.id)
        line(edge, step.id, 'back', card.id, 't-right')
      }
    })
  }
  // What leads into a step: the Orchestrator for the first wave (its request line), the steps it waited for after that
  // (the dotted order line, from their answer cards, labelled with the step's phase).
  for (const step of pattern.steps) {
    const into = requestCard.get(step.id) ?? step.id
    const intoHandle = requestCard.has(step.id) ? 't-left' : 'in'
    const running = step.status === 'running'
    if (step.column === 0) {
      edges.push({ id: `${ORCHESTRATOR}→${step.id}`, source: ORCHESTRATOR, target: into, kind: 'request', label: `${step.title} 요청`, count: 1, running, sourceHandle: 'out', targetHandle: intoHandle, ...wide })
      continue
    }
    for (const parent of parentsOf(step.id)) {
      const parentStep = byId.get(parent)
      const source = answerCard.get(parent) ?? parent
      const sourceHandle = answerCard.has(parent) ? 's-right' : 'out'
      edges.push({ id: `next:${parent}→${step.id}`, source, target: into, kind: 'next', label: step.phase ? phaseLabel(step.phase) : '다음', count: 0, running, sourceHandle, targetHandle: intoHandle, ...wide, known: !!parentStep })
    }
  }
  return { nodes, edges }
}

/** The pattern's cards alone (see patternGraph). */
export const patternNodes = (pattern: Pattern, names: Readonly<Record<string, string>> = {}, from: readonly GraphNode[] = [], messages: readonly CollaborationMessage[] = []): GraphNode[] =>
  patternGraph(pattern, names, from, messages).nodes

/** The pattern's lines alone (see patternGraph). */
export const patternLinks = (pattern: Pattern, names: Readonly<Record<string, string>> = {}, from: readonly GraphNode[] = [], messages: readonly CollaborationMessage[] = []): GraphEdge[] =>
  patternGraph(pattern, names, from, messages).edges
