import { AGENTS, type AgentSpec, agentSpec, canonicalAgent, ORCHESTRATOR, toolSpecLabel, USER } from '@/lib/agents'
import type { AgentSummary } from '@/lib/orchestrator-runs/types'

export type LiveState = 'up' | 'down' | 'unknown'

/** One agent the canvas can draw: what the conversation's folder says when there is one, else what the Orchestrator's catalog says. */
export interface CatalogEntry {
  id: string
  label: string
  /** Skill id → label in the user's words (the folder's labels when known, else the skill id in plain words). */
  tools: Readonly<Record<string, string>>
  live: LiveState | null
  /** Known to the conversation's agent folders (`lib/agents`), i.e. has a mark, a name and turn lines. */
  known: boolean
}

/** Skills every agent carries that say nothing about what it does. */
const PLUMBING = /_(health|conversation_contract|tool_catalog)$/

/** "DesignIntentAgent" → "DesignIntent Agent", "construction" → "Construction Agent". */
export function humanize(idOrLabel: string): string {
  const base = idOrLabel.replace(/[-_]+/g, ' ').replace(/\s*agent$/i, '').trim()
  const name = base.replace(/^\w/, (first) => first.toUpperCase())
  return `${name} Agent`
}

const plainTool = (tool: string) => toolSpecLabel(tool) ?? tool.replace(/^[a-z]+_/, '').replace(/_/g, ' ')

export function liveOf(status: string): LiveState | null {
  if (status === 'available') return 'up'
  if (status === 'not_declared') return null
  return 'down'
}

const fromSpec = (spec: AgentSpec, live: LiveState | null): CatalogEntry => ({ id: spec.id, label: spec.name, tools: spec.tools ?? {}, live, known: true })

/**
 * The agents to draw: the conversation's folders and the Orchestrator's catalog, merged by canonical id. An agent
 * only the catalog knows is drawn from the catalog (its label made readable, its declared skills as what it answers),
 * so a newly registered agent appears without a frontend change. The person and the Orchestrator are not agents here.
 */
export function mergeCatalog(live: readonly AgentSummary[] = [], specs: readonly AgentSpec[] = AGENTS): CatalogEntry[] {
  const entries = new Map<string, CatalogEntry>()
  for (const spec of specs) if (spec.id !== USER && spec.id !== ORCHESTRATOR) entries.set(spec.id, fromSpec(spec, null))
  for (const row of live) {
    const id = canonicalAgent(row.agent_id)
    if (id === USER || id === ORCHESTRATOR) continue
    const state = liveOf(row.connection_status)
    const spec = agentSpec(id)
    if (spec) {
      const known = entries.get(id) ?? fromSpec(spec, state)
      entries.set(id, { ...known, live: state })
      continue
    }
    const tools = Object.fromEntries(row.capabilities.filter((skill) => !PLUMBING.test(skill)).map((skill) => [skill, plainTool(skill)]))
    entries.set(id, { id, label: humanize(row.label || id), tools, live: state, known: false })
  }
  return [...entries.values()]
}

/** The entries as a name table, for places that only have an id. */
export const namesOf = (entries: readonly CatalogEntry[]): Readonly<Record<string, string>> => Object.fromEntries(entries.map((entry) => [entry.id, entry.label]))
