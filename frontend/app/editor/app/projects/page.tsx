'use client'

import dynamic from 'next/dynamic'
const ProjectsPage = dynamic(() => import('../../../planm/src/features/agent-workspace/projects/ProjectsPage'), { ssr: false })
export default function Page() { return <ProjectsPage /> }
