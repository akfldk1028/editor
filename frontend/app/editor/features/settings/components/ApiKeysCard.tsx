import { Button, Card, Input } from '@/elements/workspace'
import { Key } from 'lucide-react'
import { useTranslation } from 'react-i18next'
export function ApiKeysCard() {
  const { t } = useTranslation()
  return (
    <>
      {' '}
      {/* API Keys (placeholder) */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Key className="w-5 h-5 text-(--color-text-secondary)" />
          <h2 className="text-heading-small">{t('settings.apiKeys')}</h2>
        </div>
        <p className="text-body-medium text-(--color-text-secondary) mb-4">
          {t('settings.apiKeysDesc')}
        </p>
        <div className="flex gap-2">
          <Input placeholder="API key name" disabled />
          <Button variant="secondary" disabled>
            {t('settings.generate')}
          </Button>
        </div>
      </Card>
    </>
  )
}
