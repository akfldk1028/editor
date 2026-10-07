'use client'

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useRef, type ReactNode, type RefObject } from 'react'

import type { ArtifactManifest } from '../artifact-types'
import { useModalOverlay } from '../layout/useModalOverlay'
import type { SidebarPresentation } from '../layout/useWorkspaceControls'

export interface ShellBrand {
  mark: string
  name: string
}

interface Props {
  brand: ShellBrand
  presentation: Exclude<SidebarPresentation, 'hidden'>
  artifacts: readonly ArtifactManifest[]
  activeArtifactId: string | null
  /** Controls for the heading row, supplied by the page's modules. */
  headingActions?: ReactNode
  /** The sidebar slot below the artifact list. */
  children?: ReactNode
  restoreFocusRef?: RefObject<HTMLElement | null>
  onOpenArtifact(id: string): void
  onClose(): void
  onExpandedChange(expanded: boolean): void
}

/** Sidebar frame: heading, the registry's artifact list, then the page's sidebar slot. */
export function ShellSidebar({
  brand,
  presentation,
  artifacts,
  activeArtifactId,
  headingActions,
  children,
  restoreFocusRef,
  onOpenArtifact,
  onClose,
  onExpandedChange,
}: Props) {
  const overlay = presentation === 'drawer'
  const dialogRef = useRef<HTMLElement>(null)
  useModalOverlay({ active: overlay, dialogRef, restoreFocusRef, onClose })

  if (presentation === 'rail') {
    return (
      <aside aria-label="작업 탐색" className="workspace-sidebar rail" data-modal-background>
        <button aria-label="탐색 펼치기" className="icon-button" onClick={() => onExpandedChange(true)} title="탐색 펼치기" type="button">
          <PanelLeftOpen size={16} />
        </button>
        {artifacts.map(({ id, title, icon: Icon }) => (
          <button
            aria-label={title}
            aria-pressed={id === activeArtifactId}
            className="icon-button"
            key={id}
            onClick={() => onOpenArtifact(id)}
            title={title}
            type="button"
          >
            <Icon size={16} />
          </button>
        ))}
      </aside>
    )
  }

  return (
    <aside
      aria-label="작업 탐색"
      aria-modal={overlay ? true : undefined}
      className={`workspace-sidebar ${overlay ? 'overlay modal-overlay' : ''}`}
      data-modal-background
      ref={dialogRef}
      role={overlay ? 'dialog' : undefined}
    >
      <div className="sidebar-heading">
        <div aria-hidden="true" className="brand-mark">{brand.mark}</div><strong>{brand.name}</strong>
        <span className="sidebar-heading-actions">
          {/* In the drawer, close comes first so the dialog's initial focus lands on it. */}
          {overlay && <button aria-label="탐색 닫기" className="icon-button" onClick={onClose} title="닫기" type="button"><PanelLeftClose size={16} /></button>}
          {headingActions}
          {!overlay && <button aria-label="탐색 접기" className="icon-button" onClick={() => onExpandedChange(false)} title="탐색 접기" type="button"><PanelLeftClose size={16} /></button>}
        </span>
      </div>

      <nav aria-label="아티팩트" className="artifact-list-nav">
        {artifacts.map(({ id, title, icon: Icon }) => (
          <button
            aria-current={id === activeArtifactId ? 'true' : undefined}
            className="artifact-entry"
            key={id}
            onClick={() => onOpenArtifact(id)}
            type="button"
          >
            <Icon aria-hidden="true" size={16} /><span>{title}</span>
          </button>
        ))}
      </nav>

      {children}
    </aside>
  )
}
