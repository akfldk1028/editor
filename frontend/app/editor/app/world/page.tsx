'use client'

import dynamic from 'next/dynamic'
import Link from 'next/link'

const WorldView = dynamic(() => import('@/features/world/WorldView'), { ssr: false })

export default function Page() {
  return <div>
    <nav aria-label="지도 화면 이동" className="flex h-14 items-center gap-6 border-b border-border px-6">
      <Link href="/">3D Editor</Link>
      <Link href="/map">VWorld 지도</Link>
      <span aria-current="page">주변 맥락 3D (브이월드 없이)</span>
    </nav>
    <WorldView />
  </div>
}
