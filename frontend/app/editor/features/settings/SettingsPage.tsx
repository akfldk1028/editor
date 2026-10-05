'use client'
import { useTranslation } from 'react-i18next'
import { UISettingsCard } from './components/UISettingsCard'
import { EnvironmentVariablesCard } from './components/EnvironmentVariablesCard'
import { AppearanceCard } from './components/AppearanceCard'
import { EngineConnectionCard } from './components/EngineConnectionCard'
import { ApiKeysCard } from './components/ApiKeysCard'
export function SettingsPage() {
  const { t } = useTranslation()
  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-display-medium">{t('settings.title')}</h1>
        <p className="text-body-medium text-(--color-text-secondary) mt-1">{t('settings.desc')}</p>
      </div>
      <EngineConnectionCard />
      <AppearanceCard />
      <UISettingsCard />
      <EnvironmentVariablesCard />
      <ApiKeysCard />
    </div>
  )
}
