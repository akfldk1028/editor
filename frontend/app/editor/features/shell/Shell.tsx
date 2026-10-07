'use client'

import { useCallback, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { ArtifactHost } from './artifact-host/ArtifactHost'
import type { ShellApi } from './artifact-types'
import { ConversationSlot } from './conversation/ConversationSlot'
import { layout } from './layout/layoutModes'
import { useElementInlineSize } from './layout/useElementInlineSize'
import { useWorkspaceControls } from './layout/useWorkspaceControls'
import { useWorkspacePreferences } from './layout/useWorkspacePreferences'
import { artifactById, artifacts, defaultArtifactId } from './registry'
import { ShellSidebar, type ShellBrand } from './sidebar/ShellSidebar'
import './shell.css'

export interface ShellProps {
  brand: ShellBrand
  /** Sidebar slot below the artifact list. */
  sidebar?: ReactNode
  /** Controls for the sidebar heading row. */
  sidebarActions?: ReactNode
  conversation: {
    heading: ReactNode
    actions?: ReactNode
    /** Extra settings popover rows. */
    settings?: ReactNode
    body: ReactNode
  }
}

/** Layout numbers reach CSS only through these properties (see layout/layoutModes.ts). */
const layoutProperties = {
  '--rail-width': `${layout.sidebar.rail}px`,
  '--separator': `${layout.separatorWidth}px`,
  '--conversation-min': `${layout.conversationMinWidth}px`,
  '--artifact-min': `${layout.artifact.min}px`,
  '--drawer-max': `${layout.drawerMaxWidth}px`,
} as CSSProperties

/** `?artifact=<id>` picks the first artifact; every other query parameter is handed to it. */
function initialLocation() {
  const query = typeof window === 'undefined' ? new URLSearchParams() : new URLSearchParams(window.location.search)
  const requested = query.get('artifact')
  query.delete('artifact')
  return {
    id: artifactById(requested)?.id ?? defaultArtifactId,
    params: Object.fromEntries(query.entries()) as Record<string, string>,
  }
}

/**
 * The editor's workspace frame: sidebar | conversation | artifact. Owns the
 * layout modes (wide / medium / narrow by its own width), resizing, drawers and
 * which artifact the right-hand panel shows.
 */
export function Shell(props: ShellProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const workspaceWidth = useElementInlineSize(rootRef)
  return <div className="editor-shell" ref={rootRef}><ShellContent {...props} workspaceWidth={workspaceWidth} /></div>
}

function ShellContent({ brand, sidebar, sidebarActions, conversation, workspaceWidth }: ShellProps & { workspaceWidth: number }) {
  const workspace = useWorkspacePreferences()
  const controls = useWorkspaceControls({
    workspaceWidth,
    preferredArtifactShare: workspace.preferences.artifactShare,
    preferredSidebarWidth: workspace.preferences.sidebarWidth,
    sidebarCollapsed: workspace.preferences.sidebarCollapsed,
    setPreferredArtifactShare: workspace.setArtifactShare,
    setPreferredSidebarWidth: workspace.setSidebarWidth,
    setSidebarCollapsed: workspace.setSidebarCollapsed,
  })
  const [initial] = useState(initialLocation)
  const [artifactId, setArtifactId] = useState(initial.id)
  const [params, setParams] = useState<Record<string, string>>(initial.params)
  const [tabs, setTabs] = useState<Record<string, string>>({})
  const [textTitle, setTextTitle] = useState<{ title: string; subtitle?: string } | null>(null)
  const manifest = artifactById(artifactId) ?? artifacts[0]!
  const tab = manifest.tabs ? tabs[manifest.id] ?? manifest.tabs[0]?.id : undefined
  const { openArtifact: showArtifact, closeArtifact } = controls

  const openArtifact = useCallback((id: string, next?: Record<string, string>) => {
    if (!artifactById(id)) return
    if (id !== artifactId) {
      setTextTitle(null)
      setArtifactId(id)
    }
    if (next) setParams(next)
    showArtifact()
  }, [artifactId, showArtifact])

  const shell = useMemo<ShellApi>(() => ({
    openArtifact,
    closeArtifact,
    setTab: (next) => setTabs((current) => current[artifactId] === next ? current : { ...current, [artifactId]: next }),
    setTitle: (title, subtitle) => setTextTitle((current) => {
      if (title === null) return null
      return current?.title === title && current.subtitle === subtitle ? current : { title, subtitle }
    }),
  }), [openArtifact, closeArtifact, artifactId])

  const { mode, sidebarPresentation, artifactVisible, artifactPresentation, artifactMaximized } = controls

  return (
    <div className="app-shell" data-layout={mode} data-theme={workspace.resolvedTheme} style={layoutProperties}>
      <div
        className="workspace-grid"
        data-artifact={artifactVisible ? artifactPresentation : 'closed'}
        data-maximized={artifactMaximized && artifactVisible && artifactPresentation !== 'panel'}
        data-narrow-panel={controls.narrowPanel}
        data-sidebar={sidebarPresentation}
        style={{ '--artifact-width': `${controls.artifactWidth}px`, '--sidebar-width': `${controls.sidebarWidth}px` } as CSSProperties}
      >
        {sidebarPresentation !== 'hidden' && (
          <ShellSidebar
            activeArtifactId={artifactVisible ? manifest.id : null}
            artifacts={artifacts}
            brand={brand}
            headingActions={sidebarActions}
            onClose={controls.closeSidebar}
            onExpandedChange={controls.setSidebarExpanded}
            onOpenArtifact={(id) => {
              openArtifact(id)
              if (sidebarPresentation === 'drawer') controls.closeSidebar()
            }}
            presentation={sidebarPresentation}
            restoreFocusRef={controls.menuButtonRef}
          >
            {sidebar}
          </ShellSidebar>
        )}
        {sidebarPresentation === 'drawer' && <button aria-label="탐색 닫기" className="scrim sidebar-scrim" onClick={controls.closeSidebar} tabIndex={-1} type="button" />}
        {sidebarPresentation === 'inline' && <div className="sidebar-resizer" {...controls.sidebarSeparatorProps} />}

        <ConversationSlot
          actions={conversation.actions}
          artifactButtonRef={controls.artifactButtonRef}
          artifactLabel={manifest.label}
          artifactTitle={manifest.title}
          artifactVisible={artifactVisible}
          drawerOpen={sidebarPresentation === 'drawer'}
          heading={conversation.heading}
          menuButtonRef={controls.menuButtonRef}
          mode={mode}
          narrowPanel={controls.narrowPanel}
          onOpenArtifact={controls.openArtifact}
          onSettingsOpenChange={controls.setSettingsOpen}
          onShowNarrowPanel={controls.showNarrowPanel}
          onThemeChange={workspace.setTheme}
          onToggleSidebar={controls.toggleSidebarFromMenu}
          settings={conversation.settings}
          settingsOpen={controls.settingsOpen}
          theme={workspace.preferences.theme}
          topActionsRef={controls.topActionsRef}
        >
          <div className="shell-conversation" data-modal-background>{conversation.body}</div>
        </ConversationSlot>

        {artifactVisible && (
          <>
            {artifactPresentation === 'inline' && <div className="artifact-resizer" {...controls.artifactSeparatorProps} />}
            {artifactPresentation === 'sheet' && <button aria-label="아티팩트 배경 닫기" className="scrim artifact-scrim" onClick={closeArtifact} tabIndex={-1} type="button" />}
            <ArtifactHost
              key={manifest.id}
              manifest={manifest}
              maximized={artifactMaximized}
              onClose={closeArtifact}
              onMaximizedChange={controls.setArtifactMaximized}
              params={params}
              presentation={artifactPresentation}
              restoreFocusRef={controls.artifactButtonRef}
              shell={shell}
              tab={tab}
              textTitle={textTitle}
            />
          </>
        )}
      </div>
    </div>
  )
}
