import { useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ASSISTANT_PRESETS, SKILLS } from './assistants.constants'
import type { AssistantPreset, SkillDefinition } from './assistants.types'

/** Get localized name/description/prompts for a preset */
export function useLocalizedPreset(preset: AssistantPreset) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en-US'

  return useMemo(() => ({
    name: preset.nameI18n[locale] ?? preset.nameI18n['en-US'] ?? preset.id,
    description: preset.descriptionI18n[locale] ?? preset.descriptionI18n['en-US'] ?? '',
    prompts: preset.promptsI18n[locale] ?? preset.promptsI18n['en-US'] ?? [],
  }), [preset, locale])
}

/** Get all presets with resolved skills */
export function usePresets() {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en-US'

  const skillMap = useMemo(() => {
    const map = new Map<string, SkillDefinition>()
    for (const s of SKILLS) map.set(s.id, s)
    return map
  }, [])

  const presets = useMemo(
    () =>
      ASSISTANT_PRESETS.map((p) => ({
        ...p,
        localizedName: p.nameI18n[locale] ?? p.nameI18n['en-US'] ?? p.id,
        localizedDesc: p.descriptionI18n[locale] ?? p.descriptionI18n['en-US'] ?? '',
        localizedPrompts: p.promptsI18n[locale] ?? p.promptsI18n['en-US'] ?? [],
        resolvedSkills: p.skills.map((sid) => skillMap.get(sid)).filter(Boolean) as SkillDefinition[],
      })),
    [locale, skillMap],
  )

  const getPreset = useCallback(
    (id: string) => presets.find((p) => p.id === id),
    [presets],
  )

  return { presets, getPreset, skills: SKILLS }
}
