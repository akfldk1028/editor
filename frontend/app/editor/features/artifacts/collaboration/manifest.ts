import { ListOrdered, MessagesSquare, Workflow } from 'lucide-react'

import type { ArtifactManifest } from '../../shell/artifact-types'

/**
 * 협업: what the Orchestrator and the agents said to each other in one run — as a graph (흐름도), as
 * the readable record (대화 기록), and the project's runs to pick from. Open with `{project, run, tab}`
 * to land on one run; without params it follows the conversation's project and its newest run.
 */
export const collaborationArtifact: ArtifactManifest = {
  id: 'collaboration',
  title: '협업',
  label: '협업',
  icon: Workflow,
  tabs: [
    { id: 'flow', label: '흐름도', icon: Workflow },
    { id: 'log', label: '대화 기록', icon: MessagesSquare },
    { id: 'runs', label: '실행', icon: ListOrdered },
  ],
  load: () => import('./ui/CollaborationArtifact'),
}
