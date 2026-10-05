import { memo } from 'react'
import { Badge } from '@/elements/workspace'
import type { SkillDefinition } from '../assistants.types'

interface PresetCardProps {
  avatar: string
  name: string
  description: string
  prompts: string[]
  skills: SkillDefinition[]
  isSelected: boolean
  activeLabel: string
  onSelect: () => void
  onPromptClick: (prompt: string) => void
}

export const PresetCard = memo(function PresetCard({
  avatar,
  name,
  description,
  prompts,
  skills,
  isSelected,
  activeLabel,
  onSelect,
  onPromptClick,
}: PresetCardProps) {
  return (
    <div
      className={`rounded-xl border p-4 transition-all cursor-pointer hover:shadow-md ${
        isSelected
          ? 'border-(--color-accent-primary) ring-2 ring-(--color-accent-primary)/20 bg-(--color-accent-primary)/5'
          : 'border-(--color-border-default) bg-(--color-surface-card) hover:border-(--color-accent-primary)/50'
      }`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect() }}
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <span className="text-2xl">{avatar}</span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-(--color-text-primary) truncate">{name}</h3>
        </div>
        {isSelected && <Badge variant="primary">{activeLabel}</Badge>}
      </div>

      {/* Description */}
      <p className="text-xs text-(--color-text-secondary) mb-3 line-clamp-2">{description}</p>

      {/* Skills */}
      {skills.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {skills.map((skill) => (
            <span
              key={skill.id}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-(--color-background-secondary) text-(--color-text-tertiary)"
              title={skill.description}
            >
              {skill.icon} {skill.name}
            </span>
          ))}
        </div>
      )}

      {/* Suggested prompts */}
      {prompts.length > 0 && (
        <div className="space-y-1">
          {prompts.slice(0, 2).map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onPromptClick(prompt)
              }}
              className="w-full text-left px-2.5 py-1.5 rounded-md text-xs text-(--color-accent-primary) bg-(--color-accent-primary)/5 hover:bg-(--color-accent-primary)/10 transition-colors truncate"
              title={prompt}
            >
              &rarr; {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
})
