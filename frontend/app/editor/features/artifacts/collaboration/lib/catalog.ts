import { AGENTS, type AgentSpec, agentSpec, canonicalAgent, ORCHESTRATOR, toolSpecLabel, USER } from '@/lib/agents'
import { humanizeAgent } from '@/lib/orchestrator-runs/labels'
import type { AgentSummary } from '@/lib/orchestrator-runs/types'

export type LiveState = 'up' | 'down' | 'unknown'

/** One agent the canvas can draw: what the conversation's folder says when there is one, else what the Orchestrator's catalog says. */
export interface CatalogEntry {
  id: string
  label: string
  /** Skill id → label in the user's words (the folder's labels when known, else the card's skill name, else the id in plain words). */
  tools: Readonly<Record<string, string>>
  /** What the agent says it does (its A2A card); null when it has no card. */
  description: string | null
  live: LiveState | null
  /** Known to the conversation's agent folders (`lib/agents`), i.e. has a mark, a name and turn lines. */
  known: boolean
}

/** Skills every agent carries that say nothing about what it does. */
const PLUMBING = /_(health|conversation_contract|tool_catalog)$/

export const humanize = humanizeAgent

const plainTool = (tool: string) => toolSpecLabel(tool) ?? tool.replace(/^[a-z]+_/, '').replace(/_/g, ' ')

/**
 * The Orchestrator's connection words (its situation.py): `available`/`local` answer now, `unavailable` is down,
 * `not_declared`/`http_provider_declared` are roles without a network agent — no dot for those.
 */
export function liveOf(status: string): LiveState | null {
  if (status === 'available' || status === 'local') return 'up'
  if (status === 'unavailable') return 'down'
  return null
}

const fromSpec = (spec: AgentSpec, live: LiveState | null): CatalogEntry => ({ id: spec.id, label: spec.name, tools: spec.tools ?? {}, description: null, live, known: true })

/** The card's skills by name (plumbing dropped), else the catalog's skill ids in plain words. */
function skillsOf(row: AgentSummary): Record<string, string> {
  if (row.skills?.length) return Object.fromEntries(row.skills.filter((skill) => !PLUMBING.test(skill.id)).map((skill) => [skill.id, toolSpecLabel(skill.id) ?? skill.name]))
  return Object.fromEntries(row.capabilities.filter((skill) => !PLUMBING.test(skill)).map((skill) => [skill, plainTool(skill)]))
}

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
    const description = row.description ?? null
    const spec = agentSpec(id)
    if (spec) {
      const known = entries.get(id) ?? fromSpec(spec, state)
      // The folder's labels name the tools it knows; the card adds the skills it does not.
      entries.set(id, { ...known, tools: { ...skillsOf(row), ...known.tools }, description, live: state })
      continue
    }
    entries.set(id, { id, label: humanize(row.label || id), tools: skillsOf(row), description, live: state, known: false })
  }
  return [...entries.values()]
}

/** The entries as a name table, for places that only have an id. */
export const namesOf = (entries: readonly CatalogEntry[]): Readonly<Record<string, string>> => Object.fromEntries(entries.map((entry) => [entry.id, entry.label]))
