/**
 * The pattern a turn ran, drawn as steps: a declared cooperation workflow's steps and dependencies, or — without
 * one — the Orchestrator's own calls as the ledger timed them (same-time calls in one column, columns in order).
 * Pure: the flow draws what this returns.
 */
import { stepDone, stepStatus, stepTitle, type Workflow } from '@/lib/design-conversation/workflow'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import { callWaves, type GraphNode, NODE_HEIGHT, NODE_WIDTH } from './graph'
import { type CollaborationMessage, ORCHESTRATOR } from './transcript'

export interface PatternStep {
  id: string
  owner: string
  /** What the step does, in the user's words: the workflow step's own title or the tool's name. */
  title: string
  status: string
  code?: string
  /** 0 for the steps that start first; a step's column is one past the furthest column it waited for. */
  column: number
}
export interface PatternEdge { source: string; target: string; label?: string }
export interface Pattern { steps: PatternStep[]; edges: PatternEdge[]; declared: boolean }

/** The steps as they ran this turn: the declared workflow when there is one, else the calls' waves. */
export function patternOf(messages: readonly CollaborationMessage[], workflow?: Workflow | null, now = Date.now()): Pattern {
  if (workflow) {
    const columns = new Map<string, number>()
    const column = (id: string): number => {
      if (columns.has(id)) return columns.get(id)!
      const parents = workflow.edges.filter((edge) => edge.target === id)
      const value = parents.length ? Math.max(...parents.map((edge) => column(edge.source))) + 1 : 0
      columns.set(id, value)
      return value
    }
    const steps = Object.entries(workflow.steps).map(([id, step]) => ({ id, owner: step.owner, title: stepTitle(step), status: step.status, code: step.code, column: column(id) }))
    return { steps, edges: workflow.edges.map((edge) => ({ source: edge.source, target: edge.target })), declared: true }
  }
  const waves = callWaves(messages, now)
  const steps: PatternStep[] = waves.flatMap((wave, column) => wave.map((call, index) => ({ id: `call:${column}:${index}`, owner: call.to, title: toolLabel(call.tool), status: call.state, column })))
  // Every call of a wave began after the whole wave before it had answered: each earlier call leads to each later one.
  const edges: PatternEdge[] = waves.flatMap((wave, column) => (column ? wave.flatMap((_, index) => waves[column - 1]!.map((_, parent) => ({ source: `call:${column - 1}:${parent}`, target: `call:${column}:${index}` }))) : []))
  return { steps, edges, declared: false }
}

export const PATTERN_COLUMN = NODE_WIDTH + 110
export const PATTERN_ROW = NODE_HEIGHT + 36

/**
 * The pattern on the canvas: the person, the Orchestrator, then one column per wave of steps (centred on the row),
 * each card its owner with what it did and where it stands. Nodes carry `agent` so a click picks the owner.
 */
export function patternNodes(pattern: Pattern, names: Readonly<Record<string, string>> = {}): GraphNode[] {
  const name = (id: string) => names[id] ?? agentLabel(id)
  const base: Pick<GraphNode, 'items' | 'selected' | 'idle' | 'live' | 'order'> = { items: [], selected: false, idle: false, live: null, order: null }
  const nodes: GraphNode[] = [
    { ...base, id: 'user', agent: 'user', label: '사용자', sub: '요청', kind: 'user', position: { x: 0, y: 0 } },
    { ...base, id: ORCHESTRATOR, agent: ORCHESTRATOR, label: name(ORCHESTRATOR), sub: pattern.declared ? '함께 작업을 계획함' : '순서를 정함', kind: 'hub', position: { x: PATTERN_COLUMN, y: 0 } },
  ]
  const columns = Math.max(-1, ...pattern.steps.map((step) => step.column)) + 1
  for (let column = 0; column < columns; column += 1) {
    const wave = pattern.steps.filter((step) => step.column === column)
    wave.forEach((step, index) => {
      const state = stepStatus(step.status, step.code)
      nodes.push({ ...base, id: step.id, agent: step.owner, label: name(step.owner), sub: `${step.title} · ${state.label}`, kind: 'agent', order: column + 1,
        position: { x: PATTERN_COLUMN * (column + 2), y: (index - (wave.length - 1) / 2) * PATTERN_ROW } })
    })
  }
  return nodes
}

/** The lines of the pattern: the person to the Orchestrator, the Orchestrator to the first wave, then the dependencies. */
export function patternLinks(pattern: Pattern): { id: string; source: string; target: string; running: boolean; done: boolean }[] {
  const byId = new Map(pattern.steps.map((step) => [step.id, step]))
  const running = (id: string) => byId.get(id)?.status === 'running'
  const done = (id: string) => { const step = byId.get(id); return !!step && stepDone(step) }
  const first = pattern.steps.filter((step) => step.column === 0)
  return [
    { id: 'user>hub', source: 'user', target: ORCHESTRATOR, running: false, done: true },
    ...first.map((step) => ({ id: `hub>${step.id}`, source: ORCHESTRATOR, target: step.id, running: running(step.id), done: done(step.id) })),
    ...pattern.edges.map((edge) => ({ id: `${edge.source}>${edge.target}`, source: edge.source, target: edge.target, running: running(edge.target), done: done(edge.target) })),
  ]
}
