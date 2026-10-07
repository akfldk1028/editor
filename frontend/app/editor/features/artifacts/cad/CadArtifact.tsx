'use client'

import { useDwgArtifact } from '@click-around/workspace'

import { ArtifactChrome } from '../../shell/artifact-host/ArtifactChrome'
import type { ArtifactProps } from '../../shell/artifact-types'

/**
 * The CAD drawing artifact: the CAD package's artifact parts placed in the
 * shell's header, menu and body. Needs `DwgWorkspaceProvider` above the shell.
 */
export default function CadArtifact({ tab, shell }: ArtifactProps) {
  const view = useDwgArtifact({ tab: tab ?? 'preview', onSelectTab: shell.setTab })
  return (
    <>
      <ArtifactChrome actions={view.actions} counts={view.counts} menu={view.menu} title={view.title} />
      {view.body}
    </>
  )
}
