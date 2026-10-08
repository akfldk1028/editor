import {
  Bot, Box, Boxes, Cable, Camera, ClipboardCheck, FileText, Grid2x2, LayoutGrid, Lightbulb, ListTree, MapPin, Mountain, Scale, Sofa, UserCheck, UserRound, Workflow,
} from 'lucide-react'
import type { ComponentType } from 'react'

type Icon = ComponentType<{ size?: number; 'aria-hidden'?: boolean | 'true' }>

/** Each party's own mark: an icon (and, in CSS by `data-agent`, its own tint) — never a shared initial. */
const MARKS: Record<string, Icon> = {
  user: UserRound,
  orchestrator: Workflow,
  site_context: MapPin,
  'site-context': MapPin,
  law: Scale,
  revision: ClipboardCheck,
  masterplan: LayoutGrid,
  mass: Box,
  kmass: Boxes,
  program: ListTree,
  requirement: FileText,
  design_intent: Lightbulb,
  'design-intent': Lightbulb,
  elevation: Mountain,
  plan: Grid2x2,
  systems: Cable,
  domain_expert: UserCheck,
  'domain-expert': UserCheck,
  interior: Sofa,
  scene: Camera,
}

export function AgentMark({ agent, size = 15 }: { agent: string; size?: number }) {
  const Icon = MARKS[agent] ?? Bot
  return (
    <span aria-hidden="true" className="agent-turn-mark" data-agent={agent}>
      <Icon size={size} />
    </span>
  )
}
