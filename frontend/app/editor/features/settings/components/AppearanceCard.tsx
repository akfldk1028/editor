import { LOCALES, useLanguage } from '@/components/workspace/language'
import { useTheme } from '@/components/workspace/theme/useTheme'
import { Card, Toggle } from '@/elements/workspace'
import { Globe, Palette } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { FontScaleControl } from './FontScaleControl'
export function AppearanceCard() {
  const { t } = useTranslation()
  const { colorTheme, setColorTheme, mode, toggleMode, themes } = useTheme()
  const { currentLocale, setLocale } = useLanguage()
  return (
    <>
      {' '}
      {/* Theme + Language */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Palette className="w-5 h-5 text-(--color-text-secondary)" />
          <h2 className="text-heading-small">{t('settings.appearance')}</h2>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-label">{t('settings.darkMode')}</span>
            <Toggle checked={mode === 'dark'} onChange={toggleMode} aria-label="Toggle dark mode" />
          </div>
          <div>
            <span className="text-label block mb-2">{t('settings.colorTheme')}</span>
            <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label="Color theme">
              {themes.map((theme) => (
                <button
                  key={theme.id}
                  role="radio"
                  aria-checked={colorTheme === theme.id}
                  aria-label={`${theme.name} theme`}
                  onClick={() => setColorTheme(theme.id)}
                  className={`p-3 rounded-lg border-2 transition-all focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) ${
                    colorTheme === theme.id
                      ? 'border-(--color-accent-primary) shadow-md'
                      : 'border-(--color-border-default) hover:border-(--color-text-tertiary)'
                  }`}
                >
                  <div className="flex gap-1 mb-2">
                    <div
                      className="w-4 h-4 rounded-full"
                      style={{
                        backgroundColor:
                          mode === 'dark' ? theme.previewColors.darkBg : theme.previewColors.bg,
                      }}
                    />
                    <div
                      className="w-4 h-4 rounded-full"
                      style={{ backgroundColor: theme.previewColors.accent }}
                    />
                  </div>
                  <span className="text-body-small">{theme.name}</span>
                </button>
              ))}
            </div>
          </div>
          {/* Language selector */}
          <div className="flex items-center justify-between">
            <div>
              <span className="text-label block">{t('settings.language')}</span>
              <span className="text-body-small text-(--color-text-tertiary)">
                {t('settings.languageDesc')}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-(--color-text-tertiary)" />
              <select
                aria-label="Language"
                className="h-9 px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-sm text-(--color-text-primary)"
                value={currentLocale}
                onChange={(e) => setLocale(e.target.value as 'en-US' | 'ko-KR')}
              >
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {/* Font scale */}
          <div>
            <span className="text-label block mb-2">{t('settings.fontScale')}</span>
            <span className="text-body-small text-(--color-text-tertiary) block mb-2">
              {t('settings.fontScaleDesc')}
            </span>
            <FontScaleControl />
          </div>
        </div>
      </Card>
    </>
  )
}
