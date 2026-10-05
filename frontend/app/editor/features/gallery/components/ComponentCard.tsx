/**
 * ComponentCard - Reusable card for displaying any AutoGen component type.
 * Used inside GalleryDetail tabs for teams, agents, models, tools, etc.
 */

import { Badge, Card } from '@/elements/workspace'
import type { ComponentTypes } from '@/lib/contracts/workspace'
import { Bot, Cpu, Network, Plug, Timer, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { memo } from 'react'

const COMPONENT_ICONS: Record<ComponentTypes, typeof Bot> = {
  team: Network,
  agent: Bot,
  model: Cpu,
  tool: Wrench,
  termination: Timer,
  workbench: Plug,
}

interface ComponentCardProps {
  label: string
  provider: string
  description?: string | null
  componentType: ComponentTypes
  actions?: ReactNode
}

export const ComponentCard = memo(function ComponentCard({
  label,
  provider,
  description,
  componentType,
  actions,
}: ComponentCardProps) {
  const Icon = COMPONENT_ICONS[componentType] ?? Bot

  return (
    <Card className="flex flex-col h-full">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-(--color-background-secondary) flex items-center justify-center shrink-0">
          <Icon className="w-4.5 h-4.5 text-(--color-text-secondary)" aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-semibold text-(--color-text-primary) truncate">{label}</h4>
          <span className="mt-0.5 inline-block">
            <Badge variant="outline">{provider.split('.').pop() ?? provider}</Badge>
          </span>
        </div>
      </div>

      {description && (
        <p className="text-body-small text-(--color-text-tertiary) mt-3 line-clamp-3">
          {description}
        </p>
      )}

      {!description && (
        <p className="text-body-small text-(--color-text-tertiary) mt-3 italic">No description</p>
      )}

      {actions && <div className="flex gap-2 mt-auto pt-4">{actions}</div>}
    </Card>
  )
})
