export interface ProductRoute {
  href: string
  label: string
  sidebarLabel?: string
  translationKey?: string
  icon?: 'map' | 'rocket'
}

// Navigation belongs to the application shell, not individual feature screens.
export const productRoutes: readonly ProductRoute[] = [
  { href: '/', label: '3D Editor' },
  { href: '/dwg', label: 'CAD · DWG' },
  { href: '/planm', label: 'PLANM 평면 계획' },
  { href: '/scenes', label: '저장된 장면' },
  { href: '/projects', label: 'Projects' },
  { href: '/land', label: '토지 분석', translationKey: 'nav.land', icon: 'map' },
  { href: '/map', label: 'VWorld 지도', icon: 'map' },
  { href: '/law', label: '법규 검색', sidebarLabel: '법규 검색 · 3D 지도', icon: 'map' },
  { href: '/design', label: '매스 · 평면 설계' },
  { href: '/design/language', label: '설계 언어', sidebarLabel: '설계 언어 · 실행 근거' },
  { href: '/agents', label: 'Agents', sidebarLabel: 'A2A Agents' },
  { href: '/dialogue', label: '협업 대화', sidebarLabel: '에이전트 협업 대화' },
  { href: '/flow', label: '협업 흐름도' },
  { href: '/build', label: 'Team Builder' },
  { href: '/gallery', label: 'Gallery' },
  { href: '/history', label: 'History' },
  { href: '/deploy', label: 'Deploy', icon: 'rocket' },
  { href: '/settings', label: 'Settings', translationKey: 'nav.settings' },
]

export function isProductRouteActive(href: string, pathname: string): boolean {
  return pathname === href ||
    (href === '/scenes' && pathname.startsWith('/scene/')) ||
    (href === '/projects' && (pathname.startsWith('/projects/') || pathname.startsWith('/runs/')))
}
