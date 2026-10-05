'use client'
import { useEffect, type CSSProperties, type ReactNode } from 'react'
import { WorkspaceProviders } from './WorkspaceProviders'
import { WorkspaceSidebar } from './WorkspaceSidebar'
import { useTheme } from './theme/useTheme'
import './workspace.css'
export function WorkspaceLayout({ children }: { children: ReactNode }) {
  const theme = useTheme()
  useEffect(() => {
    theme.hydrate()
  }, [theme.hydrate])
  return (
    <WorkspaceProviders>
      <div
        className={`agent-workspace ${theme.mode === 'dark' ? 'dark' : ''} flex h-screen overflow-hidden`}
        data-theme={theme.colorTheme}
        style={{ '--workspace-font-scale': theme.scale } as CSSProperties}
      >
        <WorkspaceSidebar />
        <div className="flex flex-col flex-1 min-w-0">
          <main className="flex-1 overflow-auto p-6 bg-(--color-background-primary)">
            {children}
          </main>
        </div>
      </div>
    </WorkspaceProviders>
  )
}
