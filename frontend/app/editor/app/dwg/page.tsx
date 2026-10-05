'use client'

import dynamic from 'next/dynamic'

const DwgWorkspace = dynamic(() => import('../../../../../infra/services/dwg/apps/workspace/src/app/App').then(module => module.App), { ssr: false })

export default function Page() {
  return <div style={{ height: '100%' }}><DwgWorkspace /></div>
}
