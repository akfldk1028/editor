import type { DwgArtifactTab } from '@click-around/workspace'
import { AlertTriangle, Download, FileCheck2, FileDiff, PencilRuler, ScanSearch, View } from 'lucide-react'

import type { ArtifactManifest, ArtifactTab } from '../../shell/artifact-types'

/** Mirrors the CAD package's `dwgArtifactTabs`; ids are checked against its tab type. */
const tabs: readonly (ArtifactTab & { id: DwgArtifactTab })[] = [
  { id: 'preview', label: 'CAD Preview', icon: View },
  { id: 'findings', label: 'Findings', icon: ScanSearch },
  { id: 'changes', label: 'Changes', icon: FileDiff },
  { id: 'evidence', label: 'Evidence', icon: FileCheck2, overflow: true },
  { id: 'export', label: 'Export', icon: Download, overflow: true },
  { id: 'warnings', label: 'Warnings', icon: AlertTriangle, overflow: true },
]

export const cadArtifact: ArtifactManifest = {
  id: 'cad',
  title: 'CAD 도면',
  label: '도면',
  icon: PencilRuler,
  tabs,
  load: () => import('./CadArtifact'),
}
