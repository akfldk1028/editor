import { memo, useState, useCallback } from 'react'
import { Card } from '@/elements/workspace'
import { ChevronDown, ChevronRight, Shield } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ExtendedRegulationItem } from '@/features/land/api'

interface ExtendedRegulationsProps {
  extended: Record<string, ExtendedRegulationItem>
}

const GROUP_A_KEYS = [
  'building_use_restriction', 'site_road_requirement', 'site_subdivision_limit',
  'daylighting_spacing', 'split_zoning_rule',
]
const GROUP_B_KEYS = [
  'site_safety', 'public_open_space', 'on_site_open_space', 'structural_safety',
  'fire_resistant', 'fire_compartment', 'fire_district', 'elevator',
  'development_permit', 'infrastructure_fee',
]
const GROUP_C_KEYS = [
  'fire_protection', 'accessibility', 'energy_saving', 'evacuation',
  'finishing_materials', 'room_daylighting', 'sewage_treatment',
  'school_buffer_zone', 'cultural_heritage_zone', 'military_zone',
  'use_district_restriction', 'party_wall', 'cpted', 'combined_development',
  'basement_restriction', 'building_systems',
]

const GROUPS = [
  { labelKey: 'land.groupA', keys: GROUP_A_KEYS },
  { labelKey: 'land.groupB', keys: GROUP_B_KEYS },
  { labelKey: 'land.groupC', keys: GROUP_C_KEYS },
] as const

export const ExtendedRegulations = memo(function ExtendedRegulations({
  extended,
}: ExtendedRegulationsProps) {
  const { t } = useTranslation()
  const [isOpen, setIsOpen] = useState(false)

  const handleToggle = useCallback(() => {
    setIsOpen(prev => !prev)
  }, [])

  const count = Object.keys(extended).length

  return (
    <Card>
      <button
        type="button"
        onClick={handleToggle}
        className="flex items-center gap-2 w-full text-left"
      >
        {isOpen ? (
          <ChevronDown className="w-5 h-5 text-(--color-text-secondary)" />
        ) : (
          <ChevronRight className="w-5 h-5 text-(--color-text-secondary)" />
        )}
        <Shield className="w-5 h-5 text-(--color-text-secondary)" />
        <h3 className="text-heading-small text-(--color-text-primary)">
          {t('land.extendedRegulations')}
        </h3>
        <span className="text-label-small text-(--color-text-tertiary) ml-auto">
          {count} {t('land.items')}
        </span>
      </button>

      {isOpen && (
        <div className="mt-4 space-y-4">
          {GROUPS.map((group) => {
            const items = group.keys.flatMap((key) => {
              const item = extended[key]
              return item ? [{ key, ...item }] : []
            })
            if (items.length === 0) return null
            return (
              <div key={group.labelKey}>
                <h4 className="text-label-small text-(--color-text-tertiary) uppercase tracking-wider mb-2">
                  {t(group.labelKey)}
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {items.map((item) => (
                    <ExtendedItem key={item.key} item={item} />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
})

const ExtendedItem = memo(function ExtendedItem({
  item,
}: {
  item: ExtendedRegulationItem & { key: string }
}) {
  return (
    <div className="p-3 rounded-lg border border-(--color-border-default) bg-(--color-background-secondary)">
      <div className="flex items-start justify-between gap-2">
        <span className="text-body-small font-medium text-(--color-text-primary)">
          {item.name}
        </span>
        {item.article && (
          <span className="text-label-small text-(--color-accent-primary) shrink-0">
            {item.article}
          </span>
        )}
      </div>
      {item.rule && (
        <p className="text-body-small text-(--color-text-tertiary) mt-1 line-clamp-2">
          {item.rule}
        </p>
      )}
      {item.applies_when && (
        <p className="text-label-small text-(--color-semantic-warning) mt-1">
          {item.applies_when}
        </p>
      )}
    </div>
  )
})
