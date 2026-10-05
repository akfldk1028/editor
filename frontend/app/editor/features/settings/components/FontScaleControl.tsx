import { memo, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useFontScaleStore } from '../model/font-scale'
import {
  FONT_SCALE_DEFAULT,
  FONT_SCALE_MAX,
  FONT_SCALE_MIN,
  FONT_SCALE_STEP,
} from '../model/font-scale-constants'

const EPSILON = 0.001

export const FontScaleControl = memo(function FontScaleControl() {
  const { t } = useTranslation()
  const scale = useFontScaleStore((s) => s.scale)
  const setScale = useFontScaleStore((s) => s.setScale)
  const reset = useFontScaleStore((s) => s.reset)

  const formattedValue = useMemo(() => `${Math.round(scale * 100)}%`, [scale])
  const isDefault = Math.abs(scale - FONT_SCALE_DEFAULT) < 0.01

  const handleDecrease = useCallback(() => setScale(scale - FONT_SCALE_STEP), [scale, setScale])
  const handleIncrease = useCallback(() => setScale(scale + FONT_SCALE_STEP), [scale, setScale])

  const handleSlider = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setScale(Number(e.target.value)),
    [setScale],
  )

  return (
    <div className="flex items-center gap-2 w-full max-w-md">
      <button
        type="button"
        onClick={handleDecrease}
        disabled={scale <= FONT_SCALE_MIN + EPSILON}
        className="w-8 h-8 rounded-md border border-(--color-border-default) text-sm font-medium text-(--color-text-secondary) hover:bg-(--color-background-secondary) disabled:opacity-30 transition-colors"
        aria-label={t('settings.fontDecrease')}
      >
        -
      </button>
      <input
        type="range"
        min={FONT_SCALE_MIN}
        max={FONT_SCALE_MAX}
        step={FONT_SCALE_STEP}
        value={scale}
        onChange={handleSlider}
        className="flex-1 accent-(--color-accent-primary)"
        aria-label={t('settings.fontScale')}
      />
      <button
        type="button"
        onClick={handleIncrease}
        disabled={scale >= FONT_SCALE_MAX - EPSILON}
        className="w-8 h-8 rounded-md border border-(--color-border-default) text-sm font-medium text-(--color-text-secondary) hover:bg-(--color-background-secondary) disabled:opacity-30 transition-colors"
        aria-label={t('settings.fontIncrease')}
      >
        +
      </button>
      <span className="text-sm text-(--color-text-secondary) min-w-[48px] text-center">
        {formattedValue}
      </span>
      <button
        type="button"
        onClick={reset}
        disabled={isDefault}
        className="text-xs text-(--color-accent-primary) hover:underline disabled:opacity-30 disabled:no-underline"
        aria-label={t('settings.fontReset')}
      >
        {t('settings.fontReset')}
      </button>
    </div>
  )
})
