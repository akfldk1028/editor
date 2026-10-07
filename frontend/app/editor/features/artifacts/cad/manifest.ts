import type { DwgArtifactTab } from '@click-around/workspace'
import { AlertTriangle, Download, FileCheck2, FileDiff, PencilRuler, ScanSearch, View } from 'lucide-react'

import type { ArtifactManifest, ArtifactTab } from '../../shell/artifact-types'

/** Mirrors the CAD package's `dwgArtifactTabs`; ids are checked against its tab type. */
const tabs: readonly (ArtifactTab & { id: DwgArtifactTab })[] = [
  { id: 'preview', label: '도면 미리보기', icon: View },
  { id: 'findings', label: '검토 결과', icon: ScanSearch },
  { id: 'changes', label: '변경', icon: FileDiff },
  { id: 'evidence', label: '근거', icon: FileCheck2, overflow: true },
  { id: 'export', label: '내보내기', icon: Download, overflow: true },
  { id: 'warnings', label: '경고', icon: AlertTriangle, overflow: true },
]

export const cadArtifact: ArtifactManifest = {
  id: 'cad',
  title: 'CAD 도면',
  label: '도면',
  icon: PencilRuler,
  tabs,
  load: () => import('./CadArtifact'),
}
