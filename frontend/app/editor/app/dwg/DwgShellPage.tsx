'use client'

import {
  DwgConversation,
  DwgConversationActions,
  DwgConversationHeading,
  DwgSettings,
  DwgSidebar,
  DwgSidebarActions,
  DwgWorkspaceProvider,
} from '@click-around/workspace'

import { Shell } from '@/features/shell/Shell'

/** /dwg: the editor shell with the DWG conversation and sidebar; artifacts from the registry. */
export default function DwgShellPage() {
  return (
    <DwgWorkspaceProvider>
      <Shell
        brand={{ mark: 'DI', name: 'DWG Intelligence' }}
        conversation={{
          heading: <DwgConversationHeading />,
          actions: <DwgConversationActions />,
          settings: <DwgSettings />,
          body: <DwgConversation />,
        }}
        sidebar={<DwgSidebar />}
        sidebarActions={<DwgSidebarActions />}
      />
    </DwgWorkspaceProvider>
  )
}
