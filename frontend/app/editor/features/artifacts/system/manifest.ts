import { Activity } from 'lucide-react'

import type { ArtifactManifest } from '../../shell/artifact-types'

export const systemArtifact: ArtifactManifest = {
  id: 'system',
  title: '시스템',
  label: '시스템',
  icon: Activity,
  load: () => import('./ui/SystemArtifact'),
}
