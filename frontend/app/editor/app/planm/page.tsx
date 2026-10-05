'use client'

import dynamic from 'next/dynamic'
import '../../../planm/src/features/planm-planning/styles.css'

const PlanmPlanning = dynamic(() => import('../../../planm/src/features/planm-planning/PlanmPlanning'), { ssr: false })

export default function Page() {
  return <div className="planm-surface"><PlanmPlanning onOpenDwg={() => { window.location.href = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/dwg` }} /></div>
}
