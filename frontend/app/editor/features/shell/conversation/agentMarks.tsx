import type { CSSProperties } from 'react'

import { canonicalAgent, markOf } from '@/lib/agents'

/**
 * A party's own mark — its icon on its tint, from its folder under `lib/agents/<id>/ui/mark.tsx`.
 * The Orchestrator and the user carry no tint and are styled by `data-agent` in CSS.
 */
export function AgentMark({ agent, size = 15 }: { agent: string; size?: number }) {
  const id = canonicalAgent(agent)
  const mark = markOf(id)
  const Icon = mark.icon
  return (
    <span aria-hidden="true" className="agent-turn-mark" data-agent={id} style={mark.tint ? ({ '--mark': mark.tint } as CSSProperties) : undefined}>
      <Icon size={size} />
    </span>
  )
}
