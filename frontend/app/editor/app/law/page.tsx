'use client'

import dynamic from 'next/dynamic'
import Link from 'next/link'

const LawChat = dynamic(() => import('@/features/law/LawChat'), { ssr: false })

export default function Page() {
  return <div>
    <nav aria-label="법규 화면 이동" className="flex h-14 items-center gap-6 border-b border-border px-6">
      <Link href="/">3D Editor</Link>
      <Link href="/land">토지 규제 분석</Link>
      <Link href="/map">VWorld 지도</Link>
      <span aria-current="page">법규 검색</span>
    </nav>
    <LawChat />
  </div>
}
