'use client'

import dynamic from 'next/dynamic'
import { useRouter } from 'next/navigation'
import '@planm/features/planm-planning/styles.css'

const PlanmPlanning = dynamic(() => import('@planm/features/planm-planning/PlanmPlanning'), { ssr: false })

export default function Page() {
  // The app router moves to the CAD workspace without reloading the page (and adds the base path itself).
  const router = useRouter()
  return <div className="planm-surface"><PlanmPlanning onOpenDwg={() => { router.push('/dwg') }} /></div>
}
