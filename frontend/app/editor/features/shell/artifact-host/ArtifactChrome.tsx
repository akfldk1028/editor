'use client'

import { createContext, useContext, useLayoutEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** Header slots of the artifact host that an artifact may fill. */
export interface ArtifactHostSlots {
  title: HTMLElement | null
  actions: HTMLElement | null
  menu: HTMLElement | null
  claimTitle(claimed: boolean): void
  setCounts(counts: Readonly<Record<string, number | undefined>>): void
}

export const ArtifactHostContext = createContext<ArtifactHostSlots | null>(null)

interface Props {
  /** Replaces the host's title block (a `<strong>` title and a `<span>` status line). */
  title?: ReactNode
  /** Primary action(s) beside the title. */
  actions?: ReactNode
  /** Rows at the top of the ⋯ menu (menu-search, menu-field, menu-group). */
  menu?: ReactNode
  /** Badge counts on tabs, by tab id. */
  counts?: Readonly<Record<string, number | undefined>>
}

/**
 * Lets an artifact put rich content into the host's header and menu. The
 * content is portaled, so it re-renders with the artifact and never round-trips
 * through shell state.
 */
export function ArtifactChrome({ title, actions, menu, counts }: Props) {
  const host = useContext(ArtifactHostContext)
  const hasTitle = title !== undefined
  const countsKey = JSON.stringify(counts ?? {})

  useLayoutEffect(() => {
    if (!host || !hasTitle) return
    host.claimTitle(true)
    return () => host.claimTitle(false)
  }, [host?.claimTitle, hasTitle])

  useLayoutEffect(() => {
    host?.setCounts(JSON.parse(countsKey))
  }, [host?.setCounts, countsKey])

  if (!host) return null
  return (
    <>
      {hasTitle && host.title && createPortal(title, host.title)}
      {actions && host.actions && createPortal(actions, host.actions)}
      {menu && host.menu && createPortal(menu, host.menu)}
    </>
  )
}
