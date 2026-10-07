'use client'

import { Maximize2, Minimize2, MoreHorizontal, X } from 'lucide-react'
import { lazy, Suspense, useCallback, useId, useMemo, useRef, useState, type ComponentType, type LazyExoticComponent, type RefObject } from 'react'

import type { ArtifactManifest, ArtifactProps, ArtifactTab, ShellApi } from '../artifact-types'
import type { ArtifactPresentation } from '../layout/layoutModes'
import { useModalOverlay } from '../layout/useModalOverlay'
import { ArtifactHostContext, type ArtifactHostSlots } from './ArtifactChrome'
import { closePopover, usePopoverAnchor } from './usePopoverAnchor'

const bodies = new Map<string, LazyExoticComponent<ComponentType<ArtifactProps>>>()

function bodyFor(manifest: ArtifactManifest) {
  let body = bodies.get(manifest.id)
  if (!body) {
    body = lazy(manifest.load)
    bodies.set(manifest.id, body)
  }
  return body
}

interface Props {
  manifest: ArtifactManifest
  tab: string | undefined
  params: Readonly<Record<string, string>>
  shell: ShellApi
  /** Plain-text title set through ShellApi.setTitle. */
  textTitle: { title: string; subtitle?: string } | null
  presentation: ArtifactPresentation
  maximized: boolean
  restoreFocusRef?: RefObject<HTMLElement | null>
  onClose(): void
  onMaximizedChange(maximized: boolean): void
}

/**
 * The right-hand panel: header (title, primary action slot, ⋯ menu, close),
 * tab strip and the artifact's lazily loaded body. Remount it (key) per
 * artifact so slots and counts start fresh.
 */
export function ArtifactHost({ manifest, tab, params, shell, textTitle, presentation, maximized, restoreFocusRef, onClose, onMaximizedChange }: Props) {
  const overlay = presentation === 'sheet'
  const dialogRef = useRef<HTMLElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  useModalOverlay({ active: overlay, dialogRef, restoreFocusRef, onClose })
  usePopoverAnchor(menuRef, menuButtonRef)

  const [titleEl, setTitleEl] = useState<HTMLElement | null>(null)
  const [actionsEl, setActionsEl] = useState<HTMLElement | null>(null)
  const [menuEl, setMenuEl] = useState<HTMLElement | null>(null)
  const [titleClaimed, setTitleClaimed] = useState(false)
  const [counts, setCounts] = useState<Readonly<Record<string, number | undefined>>>({})
  const claimTitle = useCallback((claimed: boolean) => setTitleClaimed(claimed), [])
  const slots = useMemo<ArtifactHostSlots>(
    () => ({ title: titleEl, actions: actionsEl, menu: menuEl, claimTitle, setCounts }),
    [titleEl, actionsEl, menuEl, claimTitle],
  )

  const Body = bodyFor(manifest)
  const tabs = manifest.tabs ?? []
  const strip = tabs.filter((candidate) => !candidate.overflow || candidate.id === tab)
  const overflow = tabs.filter((candidate) => candidate.overflow)

  function fromMenu(action: () => void) {
    return () => {
      closePopover(menuRef.current)
      action()
    }
  }

  return (
    <section
      aria-label={manifest.title}
      aria-modal={overlay ? true : undefined}
      className={`artifact-panel ${maximized ? 'maximized' : ''} ${overlay ? 'modal-overlay' : ''}`}
      data-artifact-id={manifest.id}
      data-maximized={maximized}
      data-modal-background
      data-presentation={presentation}
      ref={dialogRef}
      role={overlay ? 'dialog' : undefined}
    >
      <div className="artifact-header">
        <div className="artifact-title">
          {!titleClaimed && (
            <>
              <strong title={textTitle?.title ?? manifest.title}>{textTitle?.title ?? manifest.title}</strong>
              {textTitle?.subtitle && <span>{textTitle.subtitle}</span>}
            </>
          )}
          <div className="shell-slot" ref={setTitleEl} />
        </div>
        <div className="shell-slot" ref={setActionsEl} />
        <button
          aria-haspopup="menu"
          aria-label="아티팩트 메뉴"
          className="icon-button"
          popoverTarget={menuId}
          ref={menuButtonRef}
          title="아티팩트 메뉴"
          type="button"
        >
          <MoreHorizontal size={16} />
        </button>
        <button aria-label={`${manifest.title} 닫기`} className="icon-button artifact-close" onClick={onClose} title="닫기" type="button">
          <X size={16} />
        </button>
        <div className="workspace-menu artifact-menu" id={menuId} popover="auto" ref={menuRef}>
          <div className="shell-slot" ref={setMenuEl} />
          {overflow.length > 0 && (
            <div aria-label="보기" className="menu-group" role="group">
              {overflow.map((candidate) => (
                <button aria-current={tab === candidate.id ? 'true' : undefined} key={candidate.id} onClick={fromMenu(() => shell.setTab(candidate.id))} type="button">
                  <TabIcon tab={candidate} /><span>{candidate.label}</span>
                  {counts[candidate.id] !== undefined && <b>{counts[candidate.id]}</b>}
                </button>
              ))}
            </div>
          )}
          {presentation !== 'panel' && (
            <div aria-label="패널" className="menu-group" role="group">
              <button aria-label={maximized ? '아티팩트 복원' : '아티팩트 최대화'} onClick={fromMenu(() => onMaximizedChange(!maximized))} type="button">
                {maximized ? <Minimize2 aria-hidden="true" size={14} /> : <Maximize2 aria-hidden="true" size={14} />}
                <span>{maximized ? '원래 크기' : '최대화'}</span>
              </button>
            </div>
          )}
        </div>
      </div>
      {strip.length > 0 && (
        <div aria-label="아티팩트 보기" className="artifact-tabs" role="tablist">
          {strip.map((candidate) => (
            <button
              aria-selected={tab === candidate.id}
              className={tab === candidate.id ? 'active' : ''}
              key={candidate.id}
              onClick={() => shell.setTab(candidate.id)}
              role="tab"
              title={candidate.label}
              type="button"
            >
              <TabIcon tab={candidate} /><span className="tab-label">{candidate.label}</span>
              {counts[candidate.id] !== undefined && <b>{counts[candidate.id]}</b>}
            </button>
          ))}
        </div>
      )}
      <div className="artifact-content">
        <ArtifactHostContext.Provider value={slots}>
          <Suspense fallback={<div className="artifact-loading"><span className="loading-mark" /> 불러오는 중</div>}>
            <Body params={params} shell={shell} tab={tab} />
          </Suspense>
        </ArtifactHostContext.Provider>
      </div>
    </section>
  )
}

function TabIcon({ tab }: { tab: ArtifactTab }) {
  const Icon = tab.icon
  return Icon ? <Icon aria-hidden="true" size={14} /> : null
}
