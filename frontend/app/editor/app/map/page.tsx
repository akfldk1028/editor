'use client'

import dynamic from 'next/dynamic'
import Link from 'next/link'

const LandMap = dynamic(() => import('@/features/land-map/LandMap'), { ssr: false })

export default function Page() {
  return <div>
    <nav aria-label="지도 화면 이동" className="flex h-14 items-center gap-6 border-b border-border px-6">
      <Link href="/">3D Editor</Link>
      <Link href="/land">토지 규제 분석</Link>
      <Link href="/law">법규 검색 · 3D 지도</Link>
      <Link href="/dialogue">에이전트 협업 대화</Link>
      <span aria-current="page">VWorld 지도</span>
    </nav>
    <LandMap />
  </div>
}
