'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'
import '@/features/design/design.css'

export default function DesignLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  return <div className="editor-design-routes">
    <nav aria-label="설계 화면 이동" className="flex h-14 items-center gap-6 border-b border-border px-6">
      {[
        ['/', '3D Editor'], ['/map', 'VWorld 지도'], ['/law', '법규 검색'],
        ['/design', '매스 · 평면 설계'], ['/design/language', '설계 언어 · 실행 근거'],
        ['/dialogue', '에이전트 대화'],
      ].map(([href, label]) => <Link key={href} href={href!} aria-current={pathname === href ? 'page' : undefined}>{label}</Link>)}
    </nav>
    {children}
  </div>
}
