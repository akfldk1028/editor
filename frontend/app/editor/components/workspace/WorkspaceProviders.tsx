'use client'
import { useEffect, useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createInstance } from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import ko from './locales/ko-KR.json'
import en from './locales/en-US.json'
export function WorkspaceProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } }),
  )
  const [i18n] = useState(() => {
    const instance = createInstance()
    void instance
      .use(initReactI18next)
      .init({
        resources: { 'ko-KR': { translation: ko }, 'en-US': { translation: en } },
        lng: 'ko-KR',
        fallbackLng: 'ko-KR',
        initAsync: false,
        interpolation: { escapeValue: false },
      })
    return instance
  })
  useEffect(() => {
    try {
      const locale = localStorage.getItem('ag-frontend-locale')
      if (locale === 'ko-KR' || locale === 'en-US') void i18n.changeLanguage(locale)
    } catch {
      /* Keep the default language. */
    }
  }, [i18n])
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </I18nextProvider>
  )
}
