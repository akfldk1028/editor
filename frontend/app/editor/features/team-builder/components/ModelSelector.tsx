/**
 * ModelSelector - Registry-powered model selection with provider grouping,
 * search, and custom model support.
 */

import { Badge, Button, Input } from '@/elements/workspace/index'
import type { ModelEntry } from '@/features/model-registry/index'
import {
  MODEL_REGISTRY,
  entryToComponent,
  filterModels,
  getModelId,
  groupByProvider,
} from '@/features/model-registry/index'
import type { Component, ModelConfig } from '@/lib/contracts/workspace'
import { ChevronDown, ChevronUp, Search } from 'lucide-react'
import { memo, useCallback, useMemo, useState } from 'react'

interface ModelSelectorProps {
  value: Component<ModelConfig> | undefined
  onChange: (model: Component<ModelConfig>) => void
}

const ModelChip = memo(function ModelChip({
  entry,
  isSelected,
  onClick,
}: {
  entry: ModelEntry
  isSelected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg border text-sm transition-all focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) ${
        isSelected
          ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary) font-medium'
          : 'border-(--color-border-default) bg-(--color-background-primary) hover:border-(--color-accent-primary)'
      }`}
      title={`${entry.model}${entry.description ? ` (${entry.description})` : ''}`}
    >
      {entry.label}
      {entry.capabilities.vision && (
        <span className="ml-1 text-xs opacity-60" title="Vision">
          👁
        </span>
      )}
      {isSelected && (
        <span className="ml-1.5">
          <Badge variant="primary">Active</Badge>
        </span>
      )}
    </button>
  )
})

export const ModelSelector = memo(function ModelSelector({ value, onChange }: ModelSelectorProps) {
  const [showCustom, setShowCustom] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [customProvider, setCustomProvider] = useState('')
  const [customModel, setCustomModel] = useState('')

  const currentModel = getModelId(value)

  const filteredModels = useMemo(() => filterModels(MODEL_REGISTRY, searchQuery), [searchQuery])

  const groups = useMemo(() => groupByProvider(filteredModels), [filteredModels])

  const handleSelect = useCallback(
    (entry: ModelEntry) => {
      onChange(entryToComponent(entry))
    },
    [onChange],
  )

  const handleCustomApply = useCallback(() => {
    if (!customModel.trim()) return
    const provider = customProvider.trim() || 'autogen_ext.models.openai.OpenAIChatCompletionClient'
    onChange({
      provider,
      component_type: 'model',
      config: {
        model: customModel.trim(),
        model_info: {
          vision: true,
          function_calling: true,
          json_output: true,
          family: 'custom',
        },
      } as ModelConfig,
    })
    setShowCustom(false)
  }, [customProvider, customModel, onChange])

  return (
    <div className="space-y-3">
      {/* Search bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-(--color-text-tertiary)" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search models..."
          className="w-full h-9 pl-9 pr-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-sm text-(--color-text-primary) placeholder:text-(--color-text-tertiary) focus:outline-none focus:border-(--color-accent-primary) focus:ring-2 focus:ring-(--color-accent-primary)/20"
        />
      </div>

      {/* Grouped model list */}
      {groups.map((group) => (
        <div key={group.family}>
          <div className="flex items-center gap-1.5 mb-1.5">
            <span className="text-sm">{group.icon}</span>
            <span className="text-xs font-semibold text-(--color-text-secondary) uppercase tracking-wide">
              {group.label}
            </span>
            <span className="text-xs text-(--color-text-tertiary)">({group.models.length})</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {group.models.map((entry) => (
              <ModelChip
                key={entry.id}
                entry={entry}
                isSelected={currentModel === entry.model}
                onClick={() => handleSelect(entry)}
              />
            ))}
          </div>
        </div>
      ))}

      {/* No results */}
      {groups.length === 0 && searchQuery && (
        <p className="text-sm text-(--color-text-tertiary)">
          No models match &quot;{searchQuery}&quot;
        </p>
      )}

      {/* Custom model toggle */}
      <button
        type="button"
        onClick={() => setShowCustom((p) => !p)}
        className="px-3 py-1.5 rounded-lg border border-dashed border-(--color-border-default) text-sm text-(--color-text-secondary) hover:border-(--color-accent-primary) transition-all focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
      >
        Custom
        {showCustom ? (
          <ChevronUp className="w-3 h-3 ml-1 inline" />
        ) : (
          <ChevronDown className="w-3 h-3 ml-1 inline" />
        )}
      </button>

      {showCustom && (
        <div className="p-3 rounded-lg bg-(--color-background-secondary) space-y-2">
          <div>
            <label className="text-xs text-(--color-text-tertiary) block mb-1">Provider</label>
            <Input
              value={customProvider}
              onChange={(e) => setCustomProvider(e.target.value)}
              placeholder="autogen_ext.models.openai.OpenAIChatCompletionClient"
            />
          </div>
          <div>
            <label className="text-xs text-(--color-text-tertiary) block mb-1">Model</label>
            <Input
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder="gpt-4o"
            />
          </div>
          <Button
            size="sm"
            variant="primary"
            onClick={handleCustomApply}
            disabled={!customModel.trim()}
          >
            Apply
          </Button>
        </div>
      )}
    </div>
  )
})
