import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MapPin, Box, Moon, Sun, Rocket } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme/useTheme'
import { isProductRouteActive, productRoutes } from './product-routes'
export function WorkspaceSidebar() {
  const { i18n } = useTranslation()
  const pathname = usePathname()
  const theme = useTheme()
  const toggleMode = theme.toggleMode
  return (
    <aside
      aria-label="Main navigation"
      className="w-60 shrink-0 h-screen flex flex-col bg-(--color-surface-card) border-r border-(--color-border-default)"
    >
      <div className="p-5 border-b border-(--color-border-default)">
        <h1 className="text-heading-medium text-(--color-text-primary) font-bold tracking-tight">
          Editor
        </h1>
        <p className="text-body-small text-(--color-text-tertiary) mt-1">
          {i18n.t('app.subtitle')}
        </p>
      </div>
      <nav className="flex-1 overflow-y-auto p-3 space-y-1">
        {productRoutes.map(({ href, label, sidebarLabel, translationKey, icon }) => {
          const Icon = icon === 'map' ? MapPin : icon === 'rocket' ? Rocket : Box
          const active = isProductRouteActive(href, pathname)
          return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium ${active ? 'bg-(--color-accent-primary-light) text-(--color-accent-primary)' : 'text-(--color-text-secondary) hover:bg-(--color-background-secondary)'}`}
          >
            <Icon className="w-5 h-5" />
            {translationKey ? i18n.t(translationKey) : sidebarLabel || label}
          </Link>
          )
        })}
      </nav>
      <div className="p-3 border-t border-(--color-border-default)">
        <button
          type="button"
          onClick={toggleMode}
          className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-(--color-text-secondary) hover:bg-(--color-background-secondary)"
        >
          {theme.mode === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
          {i18n.t(theme.mode === 'dark' ? 'nav.lightMode' : 'nav.darkMode')}
        </button>
      </div>
    </aside>
  )
}
