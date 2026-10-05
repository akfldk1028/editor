'use client'

import dynamic from 'next/dynamic'
import { useParams } from 'next/navigation'
const ProjectPage = dynamic(() => import('@planm/features/agent-workspace/projects/ProjectPage'), { ssr: false })
export default function Page() {
  const { id } = useParams<{ id: string }>()
  return <ProjectPage key={id} projectId={id} scenePath={`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/scene/`} />
}
