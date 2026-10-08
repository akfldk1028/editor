/**
 * What every agent folder under `lib/agents/<id>/` declares. One folder per party of the network
 * (the sixteen agents, the Orchestrator, the user): `model/spec.ts` says who it is and what it
 * answers, `ui/mark.tsx` how it is drawn, `lib/lines.ts` (when it has turns) what it says. The
 * registry in `index.ts` derives everything else; nothing outside a folder names an agent twice.
 */
import type { ComponentType } from 'react'

export interface AgentSpec {
  id: string
  /** Network name, in English (user, 2026-10-08); what the agent says stays Korean. */
  name: string
  /** Other ids the network uses for the same agent (hyphenated A2A ids, short names). */
  aliases?: readonly string[]
  /** Tools this agent answers, with their Korean labels; `<id>_health` is implied for every agent. */
  tools?: Readonly<Record<string, string>>
}

export type AgentIcon = ComponentType<{ size?: number; 'aria-hidden'?: boolean | 'true' }>

export interface AgentMarkSpec {
  icon: AgentIcon
  /** The agent's own tint; absent for the parties styled by `data-agent` in CSS (Orchestrator, user). */
  tint?: string
}
