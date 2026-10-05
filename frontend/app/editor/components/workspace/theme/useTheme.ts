'use client'
import { create } from 'zustand'
import { COLOR_THEMES } from './constants'
import type { ColorTheme, Mode } from './types'

type ThemeState = {
  mode: Mode
  colorTheme: ColorTheme
  themes: typeof COLOR_THEMES
  scale: number
  hydrate: () => void
  setColorTheme: (value: ColorTheme) => void
  toggleMode: () => void
  setScale: (value: number) => void
}
function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* Storage may be disabled. */
  }
}
export const useTheme = create<ThemeState>((set, get) => ({
  mode: 'light',
  colorTheme: 'default',
  themes: COLOR_THEMES,
  scale: 1,
  hydrate: () => {
    try {
      const saved = JSON.parse(localStorage.getItem('platform-theme-config') || 'null')
      const scale = Number(localStorage.getItem('ag-frontend-font-scale') || 1)
      set({
        mode:
          saved?.mode === 'dark' || (!saved && matchMedia('(prefers-color-scheme: dark)').matches)
            ? 'dark'
            : 'light',
        colorTheme: COLOR_THEMES.some((theme) => theme.id === saved?.colorTheme)
          ? saved.colorTheme
          : 'default',
        scale: Number.isFinite(scale) ? Math.min(1.5, Math.max(0.8, scale)) : 1,
      })
    } catch {
      /* Defaults remain usable without browser storage. */
    }
  },
  setColorTheme: (colorTheme) => {
    persist('platform-theme-config', JSON.stringify({ colorTheme, mode: get().mode }))
    set({ colorTheme })
  },
  toggleMode: () => {
    const mode = get().mode === 'dark' ? 'light' : 'dark'
    persist('platform-theme-config', JSON.stringify({ mode, colorTheme: get().colorTheme }))
    set({ mode })
  },
  setScale: (value) => {
    if (!Number.isFinite(value)) return
    const scale = Math.min(1.5, Math.max(0.8, Math.round(value * 100) / 100))
    persist('ag-frontend-font-scale', String(scale))
    set({ scale })
  },
}))
