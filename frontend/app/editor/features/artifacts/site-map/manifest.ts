import { Map as MapIcon } from 'lucide-react'

import type { ArtifactManifest } from '../../shell/artifact-types'

export const siteMapArtifact: ArtifactManifest = {
  id: 'site-map',
  title: '대지 지도',
  label: '지도',
  icon: MapIcon,
  load: () => import('./SiteMapArtifact'),
}
