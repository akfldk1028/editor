import { memo } from 'react'
import { Card } from '@/elements/workspace'
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

interface RestrictionsListProps {
  restrictions: string[]
}

export const RestrictionsList = memo(function RestrictionsList({
  restrictions,
}: RestrictionsListProps) {
  const { t } = useTranslation()

  if (restrictions.length === 0) return null

  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-5 h-5 text-(--color-semantic-warning)" />
        <h3 className="text-heading-small text-(--color-text-primary)">
          {t('land.restrictions')}
        </h3>
      </div>
      <div className="flex flex-wrap gap-2">
        {restrictions.map((r) => (
          <span
            key={r}
            className="inline-flex items-center px-3 py-1.5 rounded-full text-body-small bg-(--color-semantic-warning-light) text-(--color-semantic-warning) border border-(--color-semantic-warning)/20"
          >
            {r}
          </span>
        ))}
      </div>
    </Card>
  )
})
