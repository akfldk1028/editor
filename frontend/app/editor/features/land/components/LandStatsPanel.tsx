import { memo } from 'react'
import { Card } from '@/features/workspace/ui'
import { BarChart3 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { LandStats } from '@/features/land/api'

interface LandStatsPanelProps {
  stats: LandStats
}

export const LandStatsPanel = memo(function LandStatsPanel({
  stats,
}: LandStatsPanelProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-(--color-text-secondary)" />
        <h3 className="text-heading-small text-(--color-text-primary)">
          {t('land.stats')}
        </h3>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatItem label={t('land.totalQueries')} value={stats.total_queries.toLocaleString()} />
        <StatItem label={t('land.avgResponse')} value={`${Math.round(stats.avg_response_time_ms)}ms`} />
        <StatItem label={t('land.errorCount')} value={stats.error_count.toLocaleString()} />
        <StatItem
          label={t('land.topInputType')}
          value={stats.by_input_type[0]?.input_type ?? '-'}
        />
      </div>
    </Card>
  )
})

const StatItem = memo(function StatItem({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="text-center">
      <span className="text-display-small text-(--color-text-primary) block">{value}</span>
      <span className="text-label-small text-(--color-text-tertiary)">{label}</span>
    </div>
  )
})
