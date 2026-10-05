import { Badge, Card } from '@/elements/workspace'
import { Server } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useHealth, useVersion } from '../hooks/useHealth'
export function EngineConnectionCard() {
  const { t } = useTranslation()
  const { data: health } = useHealth()
  const { data: version } = useVersion()
  return (
    <>
      {' '}
      {/* Engine Connection */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Server className="w-5 h-5 text-(--color-text-secondary)" />
          <h2 className="text-heading-small">{t('settings.engine')}</h2>
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-label">Editor API</span>
            <div className="flex items-center gap-2">
              <Badge variant={health?.status ? 'success' : 'error'}>
                {health?.status ? t('settings.connected') : t('settings.disconnected')}
              </Badge>
              <span className="text-body-small text-(--color-text-tertiary)">
                /api/v1/workspace
              </span>
            </div>
          </div>
          {version && (
            <div className="flex items-center justify-between">
              <span className="text-label">{t('settings.version')}</span>
              <span className="text-body-small text-(--color-text-tertiary)">
                {version.version}
              </span>
            </div>
          )}
        </div>
      </Card>
    </>
  )
}
