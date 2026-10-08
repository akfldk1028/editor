import { BookOpen, FileText, ListChecks, Ruler, Scale } from 'lucide-react'

import type { ArtifactManifest } from '../../shell/artifact-types'

/** 법규·한계: the selected site's regulations, limits and law articles from `POST /land/analyze`. */
export const lawArtifact: ArtifactManifest = {
  id: 'law',
  title: '법규·한계',
  label: '법규',
  icon: Scale,
  tabs: [
    { id: 'summary', label: '요약', icon: FileText },
    { id: 'regulations', label: '규제', icon: ListChecks },
    { id: 'articles', label: '조문', icon: BookOpen },
    { id: 'setbacks', label: '이격선', icon: Ruler },
  ],
  load: () => import('./ui/LawArtifact'),
}
