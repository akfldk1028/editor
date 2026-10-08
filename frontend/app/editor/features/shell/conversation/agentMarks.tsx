import {
  Bot, Box, Boxes, Cable, Camera, ClipboardCheck, Coins, FileText, Grid2x2, LayoutGrid, Lightbulb, ListTree, MapPin, Mountain, Scale, Sofa, UserCheck, UserRound, Workflow,
} from 'lucide-react'
import type { ComponentType, CSSProperties } from 'react'

import { canonicalAgent } from '@/lib/orchestrator-runs/agents'

type Icon = ComponentType<{ size?: number; 'aria-hidden'?: boolean | 'true' }>

/**
 * Each party's own mark — an icon on its own tint — ONE table keyed by the canonical agent id of
 * `lib/orchestrator-runs/agents.ts` (aliases resolve there). The Orchestrator and the user are styled
 * by `data-agent` in CSS (shell accent / ink); every agent's tint lives here, so a new agent is one row.
 */
const MARKS: Record<string, { icon: Icon; tint?: string }> = {
  orchestrator: { icon: Workflow },
  user: { icon: UserRound },
  site_context: { icon: MapPin, tint: '#3d7a5a' },
  law: { icon: Scale, tint: '#4b5fb5' },
  revision: { icon: ClipboardCheck, tint: '#a65f2b' },
  masterplan: { icon: LayoutGrid, tint: '#7a4f9d' },
  mass: { icon: Box, tint: '#2f7f8f' },
  kmass: { icon: Boxes, tint: '#2f7f8f' },
  program: { icon: ListTree, tint: '#8a6d1f' },
  requirement: { icon: FileText, tint: '#8a6d1f' },
  design_intent: { icon: Lightbulb, tint: '#b0485f' },
  elevation: { icon: Mountain, tint: '#5c6b3c' },
  plan: { icon: Grid2x2, tint: '#4f7fa3' },
  systems: { icon: Cable, tint: '#6b5e8e' },
  domain_expert: { icon: UserCheck, tint: '#8a4f2b' },
  interior: { icon: Sofa, tint: '#9b5f8c' },
  scene: { icon: Camera, tint: '#5c6b3c' },
  cost: { icon: Coins, tint: '#8a6d1f' },
}

export function AgentMark({ agent, size = 15 }: { agent: string; size?: number }) {
  const id = canonicalAgent(agent)
  const mark: { icon: Icon; tint?: string } = MARKS[id] ?? { icon: Bot }
  const Icon = mark.icon
  return (
    <span aria-hidden="true" className="agent-turn-mark" data-agent={id} style={mark.tint ? ({ '--mark': mark.tint } as CSSProperties) : undefined}>
      <Icon size={size} />
    </span>
  )
}
