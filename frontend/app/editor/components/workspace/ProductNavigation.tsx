'use client'

import { usePathname } from 'next/navigation'
import './product-navigation.css'

export const productRoutes = [
  ['/', '3D Editor'], ['/dwg', 'CAD · DWG'], ['/planm', 'PLANM 평면 계획'],
  ['/scenes', '저장된 장면'], ['/projects', 'Projects'], ['/land', '토지 분석'], ['/map', 'VWorld 지도'],
  ['/law', '법규 검색'], ['/design', '매스 · 평면 설계'], ['/design/language', '설계 언어'],
  ['/agents', 'Agents'], ['/dialogue', '협업 대화'], ['/flow', '협업 흐름도'],
  ['/build', 'Team Builder'], ['/gallery', 'Gallery'], ['/history', 'History'],
  ['/deploy', 'Deploy'], ['/settings', 'Settings'],
] as const

export function ProductNavigation() {
  const pathname = usePathname()
  return <nav aria-label="제품 작업 공간" className="editor-product-navigation">
    {productRoutes.map(([href, label]) => <a key={href}
      href={`${process.env.NEXT_PUBLIC_BASE_PATH || ''}${href}`}
      aria-current={pathname === href || (href === '/scenes' && pathname.startsWith('/scene/')) ||
        (href === '/projects' && (pathname.startsWith('/projects/') || pathname.startsWith('/runs/'))) ? 'page' : undefined}
    >{label}</a>)}
  </nav>
}
