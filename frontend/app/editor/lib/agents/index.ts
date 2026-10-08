/**
 * The agent network as the conversation knows it — derived from one folder per party under
 * `lib/agents/<id>/` (see spec.ts). Everything that names an agent (turn labels, marks, tool
 * ownership, relay diagrams) reads from here; adding an agent is one folder plus one line below.
 * The Orchestrator's live catalog (`/platform/agents`) says which are up; this says what to call
 * them and what they do.
 */
import { Bot } from 'lucide-react'

import type { FeedInput } from '@/lib/orchestrator-runs/feed'
import type { RunResults } from '@/lib/orchestrator-runs/types'

import * as cost from './cost'
import * as designIntent from './design-intent'
import * as domainExpert from './domain-expert'
import * as elevation from './elevation'
import * as interior from './interior'
import * as kmass from './kmass'
import * as law from './law'
import * as mass from './mass'
import * as masterplan from './masterplan'
import * as orchestrator from './orchestrator'
import * as plan from './plan'
import * as program from './program'
import * as requirement from './requirement'
import * as revision from './revision'
import * as scene from './scene'
import * as site from './site'
import type { AgentMarkSpec, AgentSpec } from './spec'
import * as systems from './systems'
import * as user from './user'

export type { AgentIcon, AgentMarkSpec, AgentSpec } from './spec'

const FOLDERS = [orchestrator, user, site, law, revision, masterplan, mass, kmass, program, requirement, designIntent, elevation, plan, systems, domainExpert, interior, scene, cost] as const

export const ORCHESTRATOR = orchestrator.spec.id
export const USER = user.spec.id

export const AGENTS: readonly AgentSpec[] = FOLDERS.map((folder) => folder.spec)

const BY_ID = new Map<string, AgentSpec>()
const MARKS = new Map<string, AgentMarkSpec>()
for (const folder of FOLDERS) {
  BY_ID.set(folder.spec.id, folder.spec)
  MARKS.set(folder.spec.id, folder.mark)
  for (const alias of folder.spec.aliases ?? []) BY_ID.set(alias, folder.spec)
}

/** The canonical id for an id or alias; unknown ids stay as they are. */
export const canonicalAgent = (agent: string): string => BY_ID.get(agent)?.id ?? agent

export const agentSpec = (agent: string | null | undefined): AgentSpec | null => (agent ? BY_ID.get(agent) ?? null : null)

const UNKNOWN_MARK: AgentMarkSpec = { icon: Bot }

/** The agent's own mark; an unknown agent gets a plain bot. */
export const markOf = (agent: string): AgentMarkSpec => MARKS.get(canonicalAgent(agent)) ?? UNKNOWN_MARK

/** An agent's detailed turn for one of its run steps, once `results` are parsed (its folder exports `detail`). */
export type DetailLine = (results: RunResults) => FeedInput | null

const DETAILS = new Map<string, DetailLine>()
for (const folder of FOLDERS) if ('detail' in folder && typeof folder.detail === 'function') DETAILS.set(folder.spec.id, folder.detail as DetailLine)

/** The detailed line for a tool's step: the tool's owner's `detail`, or null when that agent has none yet. */
export function detailFor(tool: string): DetailLine | null {
  const owner = toolOwner(tool)
  return owner ? DETAILS.get(owner) ?? null : null
}

/** The agent that owns a tool: the one listing it, else the one whose id or alias prefixes it (`law_*`, `masterplan_*`). */
export function toolOwner(tool: string): string | null {
  for (const agent of AGENTS) if (agent.tools && tool in agent.tools) return agent.id
  const stem = tool.endsWith('_health') ? tool.slice(0, -'_health'.length) : tool
  for (const agent of AGENTS) {
    if (stem === agent.id || stem.startsWith(`${agent.id}_`)) return agent.id
    for (const alias of agent.aliases ?? []) if (stem === alias || stem.startsWith(`${alias}_`)) return agent.id
  }
  return null
}

/** The Korean label of a tool, or null when no agent lists it. */
export function toolSpecLabel(tool: string): string | null {
  for (const agent of AGENTS) {
    const label = agent.tools?.[tool]
    if (label) return label
  }
  return null
}
