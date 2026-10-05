import { useTranslation } from 'react-i18next'
export const LOCALES = [
  { code: 'en-US', label: 'English' },
  { code: 'ko-KR', label: '한국어' },
] as const
export function useLanguage() {
  const { i18n } = useTranslation()
  return {
    currentLocale: i18n.language,
    setLocale: (locale: 'en-US' | 'ko-KR') => {
      void i18n.changeLanguage(locale)
      try {
        localStorage.setItem('ag-frontend-locale', locale)
      } catch {
        /* Language still changes in this session. */
      }
    },
  }
}
