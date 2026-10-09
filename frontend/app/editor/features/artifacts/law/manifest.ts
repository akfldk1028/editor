import { BookOpen, FileText, ListChecks, Ruler, Scale, Workflow } from 'lucide-react'

import type { ArtifactManifest } from '../../shell/artifact-types'

/**
 * 법규·한계: the selected site's regulations, limits and law articles from `POST /land/analyze`, and
 * what the Orchestrator's run (대지 → 법규 → 검토 조정) returned for it. Open with `tab: 'orchestrator'`
 * to land on that tab.
 */
export const lawArtifact: ArtifactManifest = {
  id: 'law',
  title: '법규·한계',
  label: '법규',
  icon: Scale,
  tabs: [
    { id: 'review', label: '검토 조항', icon: FileText },
    { id: 'orchestrator', label: '오케스트레이터 검토', icon: Workflow },
    { id: 'regulations', label: '규제', icon: ListChecks },
    { id: 'articles', label: '조문', icon: BookOpen },
    { id: 'setbacks', label: '이격선', icon: Ruler },
  ],
  load: () => import('./ui/LawArtifact'),
}
