import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MapPin, Box, Moon, Sun, Rocket } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useTheme } from './theme/useTheme'
export function WorkspaceSidebar() {
  const { i18n } = useTranslation()
  const pathname = usePathname()
  const theme = useTheme()
  const toggleMode = theme.toggleMode
  const navigation = [
    { href: '/', label: '3D Editor', Icon: Box },
    { href: '/land', label: i18n.t('nav.land'), Icon: MapPin },
    { href: '/map', label: 'VWorld 지도', Icon: MapPin },
    { href: '/law', label: '법규 검색 · 3D 지도', Icon: MapPin },
    { href: '/design', label: '매스 · 평면 설계', Icon: Box },
    { href: '/design/language', label: '설계 언어 · 실행 근거', Icon: Box },
    { href: '/agents', label: 'A2A Agents', Icon: Box },
    { href: '/dialogue', label: '에이전트 협업 대화', Icon: Box },
    { href: '/flow', label: '협업 흐름도', Icon: Box },
    { href: '/build', label: 'Team Builder', Icon: Box },
    { href: '/gallery', label: 'Gallery', Icon: Box },
    { href: '/history', label: 'History', Icon: Box },
    { href: '/deploy', label: 'Deploy', Icon: Rocket },
    { href: '/settings', label: i18n.t('nav.settings'), Icon: Box },
  ]
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
        {navigation.map(({ href, label, Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={pathname === href ? 'page' : undefined}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium ${pathname === href ? 'bg-(--color-accent-primary-light) text-(--color-accent-primary)' : 'text-(--color-text-secondary) hover:bg-(--color-background-secondary)'}`}
          >
            <Icon className="w-5 h-5" />
            {label}
          </Link>
        ))}
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
