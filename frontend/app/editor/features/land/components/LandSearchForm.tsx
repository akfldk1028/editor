import { memo, useState, useCallback } from 'react'
import { Button, Input } from '@/features/workspace/ui'
import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { LandAnalyzeRequest } from '@/features/land/api'
import type { LandZone } from '@/features/land/api'

interface LandSearchFormProps {
  zones: LandZone[] | undefined
  isLoading: boolean
  onSubmit: (req: LandAnalyzeRequest) => void
}

function isPnu(value: string): boolean {
  return /^\d{19}$/.test(value.replace(/-/g, ''))
}

export const LandSearchForm = memo(function LandSearchForm({
  zones,
  isLoading,
  onSubmit,
}: LandSearchFormProps) {
  const { t } = useTranslation()
  const [inputValue, setInputValue] = useState('')
  const [inputType, setInputType] = useState<'address' | 'pnu'>('address')
  const [selectedZone, setSelectedZone] = useState('')

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setInputValue(val)
    if (isPnu(val)) {
      setInputType('pnu')
    } else if (val.length > 0 && !/^\d+$/.test(val.replace(/-/g, ''))) {
      setInputType('address')
    }
  }, [])

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    if (!inputValue.trim()) return
    const req: LandAnalyzeRequest = {
      input: inputValue.trim(),
      input_type: inputType,
      include_law: true,
    }
    if (selectedZone) {
      req.zones = [selectedZone]
    }
    onSubmit(req)
  }, [inputValue, inputType, selectedZone, onSubmit])

  const handleTypeToggle = useCallback((type: 'address' | 'pnu') => {
    setInputType(type)
  }, [])

  const handleZoneChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedZone(e.target.value)
  }, [])

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-(--color-border-default) overflow-hidden">
          <button
            type="button"
            onClick={() => handleTypeToggle('address')}
            className={`px-3 py-1.5 text-sm transition-colors ${
              inputType === 'address'
                ? 'bg-(--color-accent-primary) text-white'
                : 'bg-(--color-surface-card) text-(--color-text-secondary) hover:bg-(--color-background-secondary)'
            }`}
          >
            {t('land.address')}
          </button>
          <button
            type="button"
            onClick={() => handleTypeToggle('pnu')}
            className={`px-3 py-1.5 text-sm transition-colors ${
              inputType === 'pnu'
                ? 'bg-(--color-accent-primary) text-white'
                : 'bg-(--color-surface-card) text-(--color-text-secondary) hover:bg-(--color-background-secondary)'
            }`}
          >
            PNU
          </button>
        </div>
        <div className="flex-1">
          <Input
            value={inputValue}
            onChange={handleInputChange}
            placeholder={t('land.searchPlaceholder')}
            aria-label={t('land.searchPlaceholder')}
          />
        </div>
        <Button type="submit" disabled={isLoading || !inputValue.trim()}>
          <Search className="w-4 h-4 mr-2" />
          {t('land.analyze')}
        </Button>
      </div>
      <div className="flex items-center gap-2">
        <label
          htmlFor="zone-select"
          className="text-label-small text-(--color-text-tertiary) shrink-0"
        >
          {t('land.zoneOverride')}
        </label>
        <select
          id="zone-select"
          value={selectedZone}
          onChange={handleZoneChange}
          className="h-9 px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-(--color-text-primary) text-sm focus:outline-none focus:border-(--color-accent-primary)"
        >
          <option value="">{t('land.autoDetect')}</option>
          {zones?.map((z) => (
            <option key={z.zone_name} value={z.zone_name}>
              {z.zone_name} (BCR {z.bcr_default}% / FAR {z.far_default}%)
            </option>
          ))}
        </select>
      </div>
    </form>
  )
})
