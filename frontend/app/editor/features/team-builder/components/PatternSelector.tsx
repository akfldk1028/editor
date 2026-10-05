/**
 * PatternSelector - Shows 5 pattern cards with current pattern highlighted
 * Read-only in Phase 2c; pattern switching comes in Phase 3
 */

import { Badge } from '@/elements/workspace/index'
import { ArrowRight, MessagesSquare, Repeat, Shuffle, Target, type LucideIcon } from 'lucide-react'
import { memo } from 'react'
import type { PatternType } from '../agentflow/types'
import { PATTERN_DEFINITIONS } from '../agentflow/types'

interface PatternSelectorProps {
  currentPattern: PatternType
  onSelect?: (pattern: PatternType) => void
}

const PATTERN_ICONS: Record<string, LucideIcon> = {
  'arrow-right': ArrowRight,
  target: Target,
  shuffle: Shuffle,
  'messages-square': MessagesSquare,
  repeat: Repeat,
}

const DISPLAY_PATTERNS: PatternType[] = [
  'sequential',
  'selector',
  'handoff',
  'debate',
  'reflection',
]

export const PatternSelector = memo(function PatternSelector({
  currentPattern,
  onSelect,
}: PatternSelectorProps) {
  return (
    <div className="flex flex-wrap gap-2 mb-3" role="radiogroup" aria-label="Team pattern selector">
      {DISPLAY_PATTERNS.map((id) => {
        const def = PATTERN_DEFINITIONS[id]
        if (!def) return null
        const Icon = PATTERN_ICONS[def.visual.icon]
        const isCurrent = id === currentPattern

        return (
          <div
            key={id}
            role="radio"
            aria-checked={isCurrent}
            tabIndex={isCurrent ? 0 : -1}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all ${
              onSelect ? 'cursor-pointer' : 'cursor-default'
            } ${
              isCurrent
                ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary)'
                : 'border-(--color-border-default) bg-(--color-background-primary)'
            }`}
            onClick={onSelect ? () => onSelect(id) : undefined}
            onKeyDown={
              onSelect
                ? (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSelect(id)
                    }
                  }
                : undefined
            }
          >
            {Icon && (
              <Icon className="w-4 h-4 flex-shrink-0" style={{ color: def.visual.primaryColor }} />
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium text-(--color-text-primary)">{def.name}</span>
                {isCurrent && <Badge variant="primary">Current</Badge>}
              </div>
              <p className="text-xs text-(--color-text-tertiary) truncate">{def.description}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
})
