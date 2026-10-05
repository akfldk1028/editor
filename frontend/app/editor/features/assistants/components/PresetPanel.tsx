import { memo, useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import { usePresets } from '../assistants.hooks'
import { PresetCard } from './PresetCard'

type CategoryFilter = 'all' | 'productivity' | 'creative' | 'development' | 'lifestyle'

const CATEGORY_TABS: { key: CategoryFilter; labelKey: string }[] = [
  { key: 'all', labelKey: 'assistants.filterAll' },
  { key: 'productivity', labelKey: 'assistants.filterProductivity' },
  { key: 'creative', labelKey: 'assistants.filterCreative' },
  { key: 'development', labelKey: 'assistants.filterDevelopment' },
  { key: 'lifestyle', labelKey: 'assistants.filterLifestyle' },
]

interface PresetPanelProps {
  selectedPresetId: string | null
  onSelectPreset: (presetId: string) => void
  onPromptClick: (prompt: string) => void
}

export const PresetPanel = memo(function PresetPanel({
  selectedPresetId,
  onSelectPreset,
  onPromptClick,
}: PresetPanelProps) {
  const { t } = useTranslation()
  const { presets } = usePresets()
  const [collapsed, setCollapsed] = useState(false)
  const [category, setCategory] = useState<CategoryFilter>('all')

  const handleToggle = useCallback(() => {
    setCollapsed((p) => !p)
  }, [])

  const filtered = category === 'all'
    ? presets
    : presets.filter((p) => p.category === category)

  return (
    <div className="border-b border-(--color-border-default) bg-(--color-background-primary)">
      {/* Toggle header */}
      <button
        type="button"
        onClick={handleToggle}
        className="flex items-center gap-2 w-full px-4 py-2.5 text-left hover:bg-(--color-background-secondary) transition-colors"
      >
        <Sparkles className="w-4 h-4 text-(--color-accent-primary)" />
        <span className="text-xs font-semibold text-(--color-text-secondary) uppercase tracking-wide flex-1">
          {t('assistants.title')}
        </span>
        <span className="text-xs text-(--color-text-tertiary)">{presets.length}</span>
        {collapsed ? (
          <ChevronDown className="w-4 h-4 text-(--color-text-tertiary)" />
        ) : (
          <ChevronUp className="w-4 h-4 text-(--color-text-tertiary)" />
        )}
      </button>

      {/* Category filter + Preset grid */}
      {!collapsed && (
        <div className="px-4 pb-4">
          {/* Category tabs */}
          <div className="flex gap-1 mb-3">
            {CATEGORY_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setCategory(tab.key)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  category === tab.key
                    ? 'bg-(--color-accent-primary) text-white'
                    : 'bg-(--color-background-secondary) text-(--color-text-tertiary) hover:text-(--color-text-secondary)'
                }`}
              >
                {t(tab.labelKey)}
              </button>
            ))}
          </div>

          {/* Preset grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
            {filtered.map((preset) => (
              <PresetCard
                key={preset.id}
                avatar={preset.avatar}
                name={preset.localizedName}
                description={preset.localizedDesc}
                prompts={preset.localizedPrompts}
                skills={preset.resolvedSkills}
                isSelected={selectedPresetId === preset.id}
                activeLabel={t('assistants.active')}
                onSelect={() => onSelectPreset(preset.id)}
                onPromptClick={onPromptClick}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
})
