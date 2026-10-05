import { memo } from 'react'
import { Card } from '@/elements/workspace'
import { Scale } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { RegulationsResponse } from '@/features/land/api'

interface RegulationSummaryProps {
  regulations: RegulationsResponse
}

interface RegDisplayItem {
  key: string
  labelKey: string
  value: string
  hasValue: boolean
}

function formatRegulations(reg: RegulationsResponse): RegDisplayItem[] {
  return [
    {
      key: 'bcr',
      labelKey: 'land.bcr',
      value: reg.bcr.limit_pct != null ? `${reg.bcr.limit_pct}%` : '-',
      hasValue: reg.bcr.limit_pct != null,
    },
    {
      key: 'far',
      labelKey: 'land.far',
      value: reg.far.limit_pct != null ? `${reg.far.limit_pct}%` : '-',
      hasValue: reg.far.limit_pct != null,
    },
    {
      key: 'height',
      labelKey: 'land.height',
      value: reg.height.limit_m != null ? `${reg.height.limit_m}m` : '-',
      hasValue: reg.height.limit_m != null,
    },
    {
      key: 'sunlight',
      labelKey: 'land.sunlight',
      value: reg.sunlight_setback.applies ? reg.sunlight_setback.direction ?? 'Y' : '-',
      hasValue: reg.sunlight_setback.applies === true,
    },
    {
      key: 'corner',
      labelKey: 'land.cornerCutoff',
      value: reg.corner_cutoff.required ? 'Y' : '-',
      hasValue: reg.corner_cutoff.required === true,
    },
    {
      key: 'road',
      labelKey: 'land.roadDiagonal',
      value: reg.road_diagonal.multiplier != null ? `×${reg.road_diagonal.multiplier}` : '-',
      hasValue: reg.road_diagonal.multiplier != null,
    },
    {
      key: 'line',
      labelKey: 'land.buildingLine',
      value: reg.building_line.setback_m != null ? `${reg.building_line.setback_m}m` : '-',
      hasValue: reg.building_line.setback_m != null,
    },
    {
      key: 'adjacent',
      labelKey: 'land.adjacentSetback',
      value: reg.adjacent_setback.min_m != null ? `${reg.adjacent_setback.min_m}m` : '-',
      hasValue: reg.adjacent_setback.min_m != null,
    },
    {
      key: 'parking',
      labelKey: 'land.parking',
      value: reg.parking.rule || '-',
      hasValue: !!reg.parking.rule,
    },
    {
      key: 'landscaping',
      labelKey: 'land.landscaping',
      value: reg.landscaping.min_pct != null ? `${reg.landscaping.min_pct}%` : '-',
      hasValue: reg.landscaping.min_pct != null,
    },
  ]
}

export const RegulationSummary = memo(function RegulationSummary({
  regulations,
}: RegulationSummaryProps) {
  const { t } = useTranslation()
  const items = formatRegulations(regulations)

  return (
    <Card>
      <div className="flex items-center gap-2 mb-4">
        <Scale className="w-5 h-5 text-(--color-text-secondary)" />
        <h3 className="text-heading-small text-(--color-text-primary)">
          {t('land.coreRegulations')}
        </h3>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {items.map((item) => (
          <div
            key={item.key}
            className={`p-3 rounded-lg border ${
              item.hasValue
                ? 'border-(--color-accent-primary)/30 bg-(--color-accent-primary-light)'
                : 'border-(--color-border-default) bg-(--color-background-secondary)'
            }`}
          >
            <span className="text-label-small text-(--color-text-tertiary) block">
              {t(item.labelKey)}
            </span>
            <span className={`text-body-large font-semibold ${
              item.hasValue
                ? 'text-(--color-accent-primary)'
                : 'text-(--color-text-tertiary)'
            }`}>
              {item.value}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
})
