'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { ArtifactHost } from './artifact-host/ArtifactHost'
import type { ShellApi } from './artifact-types'
import { AgentConversation, AgentConversationActions, AgentConversationHeading } from './conversation/AgentConversation'
import { AgentFeed } from './conversation/AgentFeed'
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
    persistPreferences: workspace.persist,
  })
  const [initial] = useState(initialLocation)
  const [artifactId, setArtifactId] = useState(initial.id)
  const [params, setParams] = useState<Record<string, string>>(initial.params)
  // The artifact shown before this one, so the flow (opened from the map, the law reader, CAD …) can lead back to it.
  const [previous, setPrevious] = useState<{ id: string; params: Record<string, string> } | null>(null)
  const [tabs, setTabs] = useState<Record<string, string>>({})
  const [textTitle, setTextTitle] = useState<{ title: string; subtitle?: string } | null>(null)
  const manifest = artifactById(artifactId) ?? artifacts[0]!
  const tab = manifest.tabs ? tabs[manifest.id] ?? manifest.tabs[0]?.id : undefined
  const { openArtifact: showArtifact, closeArtifact } = controls

  const openArtifact = useCallback((id: string, next?: Record<string, string>) => {
    if (!artifactById(id)) return
    if (id !== artifactId) {
      setPrevious({ id: artifactId, params })
      setTextTitle(null)
      setArtifactId(id)
    }
    if (next) setParams(next)
    showArtifact()
  }, [artifactId, params, showArtifact])

  const shell = useMemo<ShellApi>(() => ({
    openArtifact,
    closeArtifact,
    setTab: (next) => setTabs((current) => current[artifactId] === next ? current : { ...current, [artifactId]: next }),
    setTitle: (title, subtitle) => setTextTitle((current) => {
      if (title === null) return null
      return current?.title === title && current.subtitle === subtitle ? current : { title, subtitle }
    }),
  }), [openArtifact, closeArtifact, artifactId])

  const { mode, sidebarPresentation, artifactVisible, artifactMounted, artifactPresentation, artifactMaximized } = controls
  // The centre column: the agent conversation, unless the active artifact brings the page's own (CAD).
  const pageConversation = manifest.conversation === 'page'

  // Closing from the artifact's own X sends focus to the button that brings it back, once that button is drawn.
  const focusAfterClose = useRef(false)
  const closeFromArtifact = useCallback(() => {
    focusAfterClose.current = true
    closeArtifact()
  }, [closeArtifact])
  const { artifactButtonRef } = controls
  useEffect(() => {
    if (artifactVisible || !focusAfterClose.current) return
    focusAfterClose.current = false
    const frame = requestAnimationFrame(() => artifactButtonRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [artifactVisible, artifactButtonRef])

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
          actions={pageConversation ? conversation.actions : <AgentConversationActions />}
          artifactButtonRef={controls.artifactButtonRef}
          artifactLabel={manifest.label}
          artifactTitle={manifest.title}
          artifactVisible={artifactVisible}
          drawerOpen={sidebarPresentation === 'drawer'}
          heading={pageConversation ? conversation.heading : <AgentConversationHeading />}
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
          <div className="shell-conversation" data-modal-background>
            {pageConversation ? (
              <>
                <AgentFeed shell={shell} />
                {conversation.body}
              </>
            ) : (
              <AgentConversation shell={shell} />
            )}
          </div>
        </ConversationSlot>

        {artifactMounted && (
          <>
            {artifactVisible && artifactPresentation === 'inline' && <div className="artifact-resizer" {...controls.artifactSeparatorProps} />}
            {artifactVisible && artifactPresentation === 'sheet' && <button aria-label="아티팩트 배경 닫기" className="scrim artifact-scrim" onClick={closeArtifact} tabIndex={-1} type="button" />}
            <ArtifactHost
              hidden={!artifactVisible}
              key={manifest.id}
              manifest={manifest}
              maximized={artifactMaximized}
              onClose={closeFromArtifact}
              onMaximizedChange={controls.setArtifactMaximized}
              params={params}
              presentation={artifactPresentation}
              // The way back: the artifact shown before, else (the flow opened straight from a link) the shell's default.
              previous={previous && previous.id !== manifest.id ? previous : manifest.id !== defaultArtifactId ? { id: defaultArtifactId, params: {} } : null}
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
