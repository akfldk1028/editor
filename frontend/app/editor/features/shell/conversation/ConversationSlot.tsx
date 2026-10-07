'use client'

import { Menu, MessageSquare, PanelRight, Settings2, View } from 'lucide-react'
import type { ReactNode, RefObject } from 'react'

import type { LayoutMode } from '../layout/layoutModes'
import type { NarrowPanel } from '../layout/useWorkspaceControls'
import type { ThemePreference } from '../layout/workspacePreferences'

interface Props {
  mode: LayoutMode
  /** The conversation module's identity block for the header row. */
  heading: ReactNode
  /** The conversation module's header controls (e.g. new conversation). */
  actions?: ReactNode
  /** Extra rows for the settings popover. */
  settings?: ReactNode
  /** The conversation itself; renders its own `.conversation-panel` cell. */
  children: ReactNode
  drawerOpen: boolean
  narrowPanel: NarrowPanel
  artifactVisible: boolean
  artifactTitle: string
  artifactLabel: string
  settingsOpen: boolean
  theme: ThemePreference
  menuButtonRef: RefObject<HTMLButtonElement | null>
  artifactButtonRef: RefObject<HTMLButtonElement | null>
  topActionsRef: RefObject<HTMLDivElement | null>
  onToggleSidebar(): void
  onShowNarrowPanel(panel: NarrowPanel): void
  onOpenArtifact(): void
  onSettingsOpenChange(update: (open: boolean) => boolean): void
  onThemeChange(theme: ThemePreference): void
}

/**
 * The conversation column: one header row (menu, heading, narrow panel switch,
 * actions, settings) above the conversation the page supplies.
 */
export function ConversationSlot(props: Props) {
  const { mode, narrowPanel } = props
  return (
    <>
      <header className="topbar" data-modal-background>
        {mode !== 'wide' && (
          <button
            aria-expanded={props.drawerOpen}
            aria-label="탐색 열기"
            className="icon-button menu-button"
            onClick={props.onToggleSidebar}
            ref={props.menuButtonRef}
            title="탐색"
            type="button"
          >
            <Menu size={18} />
          </button>
        )}
        {props.heading}
        {mode === 'narrow' && (
          <div aria-label="패널 전환" className="panel-switch" role="group">
            <button aria-pressed={narrowPanel === 'conversation'} onClick={() => props.onShowNarrowPanel('conversation')} type="button">
              <MessageSquare aria-hidden="true" size={14} /><span>대화</span>
            </button>
            <button aria-pressed={narrowPanel === 'artifact'} onClick={() => props.onShowNarrowPanel('artifact')} ref={props.artifactButtonRef} type="button">
              <View aria-hidden="true" size={14} /><span>{props.artifactLabel}</span>
            </button>
          </div>
        )}
        <div className="topbar-actions" ref={props.topActionsRef}>
          {props.actions}
          {mode !== 'narrow' && !props.artifactVisible && (
            <button
              aria-label={`${props.artifactTitle} 열기`}
              className="icon-button artifact-toggle"
              onClick={props.onOpenArtifact}
              ref={props.artifactButtonRef}
              title={`${props.artifactTitle} 열기`}
              type="button"
            >
              <PanelRight size={17} />
            </button>
          )}
          <div className="settings-anchor">
            <button
              aria-expanded={props.settingsOpen}
              aria-label="설정"
              className="icon-button"
              onClick={() => props.onSettingsOpenChange((open) => !open)}
              title="설정 · 알림"
              type="button"
            >
              <Settings2 size={17} />
            </button>
            {props.settingsOpen && (
              <div aria-label="뷰어 설정" className="settings-popover" role="dialog">
                <label>
                  <span>테마</span>
                  <select aria-label="테마" onChange={(event) => props.onThemeChange(event.target.value as ThemePreference)} value={props.theme}>
                    <option value="system">시스템</option>
                    <option value="light">밝게</option>
                    <option value="dark">어둡게</option>
                  </select>
                </label>
                {props.settings}
                <div className="settings-notifications">
                  <span>알림</span>
                  <p className="notification-popover" role="status">새 알림이 없습니다.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>
      {props.children}
    </>
  )
}
