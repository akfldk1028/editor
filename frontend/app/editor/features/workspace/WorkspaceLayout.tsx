'use client'

import { useEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MapPin, Box, Moon, Sun } from 'lucide-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createInstance } from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import ko from './locales/ko-KR.json'
import en from './locales/en-US.json'
import './workspace.css'

export function WorkspaceLayout({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } }))
  const [i18n] = useState(() => {
    const instance = createInstance()
    void instance.use(initReactI18next).init({ resources: { 'ko-KR': { translation: ko }, 'en-US': { translation: en } }, lng: 'ko-KR', fallbackLng: 'ko-KR', initAsync: false, interpolation: { escapeValue: false } })
    return instance
  })
  const [theme, setTheme] = useState({ mode: 'light', colorTheme: 'default' })
  const pathname = usePathname()
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('platform-theme-config') || 'null')
      setTheme({ mode: saved?.mode === 'dark' || (!saved && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light', colorTheme: ['default', 'dusk', 'lime', 'ocean', 'retro', 'neo', 'forest'].includes(saved?.colorTheme) ? saved.colorTheme : 'default' })
    } catch { /* Storage is optional for route rendering. */ }
  }, [])
  function toggleMode() {
    const next = { ...theme, mode: theme.mode === 'dark' ? 'light' : 'dark' }
    setTheme(next)
    try { localStorage.setItem('platform-theme-config', JSON.stringify(next)) } catch { /* Keep the selected mode in memory. */ }
  }
  return <I18nextProvider i18n={i18n}><QueryClientProvider client={queryClient}>
    <div className={`agent-workspace ${theme.mode === 'dark' ? 'dark' : ''} flex h-screen overflow-hidden`} data-theme={theme.colorTheme}>
      <aside aria-label="Main navigation" className="w-60 shrink-0 h-screen flex flex-col bg-(--color-surface-card) border-r border-(--color-border-default)">
        <div className="p-5 border-b border-(--color-border-default)">
          <h1 className="text-heading-medium text-(--color-text-primary) font-bold tracking-tight">Editor</h1>
          <p className="text-body-small text-(--color-text-tertiary) mt-1">{i18n.t('app.subtitle')}</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <Link href="/" className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-(--color-text-secondary) hover:bg-(--color-background-secondary)"><Box className="w-5 h-5" />3D Editor</Link>
          <Link href="/land" aria-current={pathname === '/land' ? 'page' : undefined} className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium bg-(--color-accent-primary-light) text-(--color-accent-primary)"><MapPin className="w-5 h-5" />{i18n.t('nav.land')}</Link>
        </nav>
        <div className="p-3 border-t border-(--color-border-default)"><button type="button" onClick={toggleMode} className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-(--color-text-secondary) hover:bg-(--color-background-secondary)">{theme.mode === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}{i18n.t(theme.mode === 'dark' ? 'nav.lightMode' : 'nav.darkMode')}</button></div>
      </aside>
      <div className="flex flex-col flex-1 min-w-0">
        <header className="h-14 shrink-0 flex items-center justify-between px-6 border-b border-(--color-border-default) bg-(--color-surface-card)"><span className="text-label-small text-(--color-accent-primary)">Editor</span></header>
        <main className="flex-1 overflow-auto p-6 bg-(--color-background-primary)">{children}</main>
      </div>
    </div>
  </QueryClientProvider></I18nextProvider>
}
