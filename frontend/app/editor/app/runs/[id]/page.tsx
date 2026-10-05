'use client'

import dynamic from 'next/dynamic'
import { useParams } from 'next/navigation'
const RunPage = dynamic(() => import('@planm/features/agent-workspace/runs/RunPage'), { ssr: false })
export default function Page() {
  const { id } = useParams<{ id: string }>()
  return <RunPage key={id} runId={id} />
}
