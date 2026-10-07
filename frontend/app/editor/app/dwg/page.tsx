'use client'

import dynamic from 'next/dynamic'

const DwgShellPage = dynamic(() => import('./DwgShellPage'), { ssr: false })

export default function Page() {
  return <div style={{ height: '100%' }}><DwgShellPage /></div>
}
