import type { ComponentType } from 'react'

/** Lucide-compatible icon component. */
export type ArtifactIcon = ComponentType<{ size?: number; 'aria-hidden'?: boolean | 'true' }>

export interface ArtifactTab {
  id: string
  label: string
  icon?: ArtifactIcon
  /** Opens from the ⋯ menu and joins the tab strip only while active. */
  overflow?: boolean
}

/**
 * One kind of content the right-hand panel can show. `load` is called the
 * first time the artifact opens, so an artifact's code stays out of the
 * shell's own bundle.
 */
export interface ArtifactManifest {
  id: string
  /** Header title until the artifact sets its own; also the sidebar entry. */
  title: string
  /** Short label for the narrow-layout panel switch. */
  label: string
  icon: ArtifactIcon
  /** First entry is the default view. Omitted: no tab strip. */
  tabs?: readonly ArtifactTab[]
  /**
   * What the centre column shows while this artifact is active: the Orchestrator conversation
   * (default, `'agents'`) or the page's own conversation (`'page'`, e.g. the CAD drawing chat).
   */
  conversation?: 'agents' | 'page'
  load(): Promise<{ default: ComponentType<ArtifactProps> }>
}

export interface ArtifactProps {
  /** Active tab id (one of the manifest's tabs), undefined without tabs. */
  tab?: string
  /** Parameters the artifact was opened with (also the page's query string). */
  params: Readonly<Record<string, string>>
  shell: ShellApi
}

export interface ShellApi {
  openArtifact(id: string, params?: Record<string, string>): void
  closeArtifact(): void
  setTab(tab: string): void
  /** Plain-text header title; null restores the manifest title. */
  setTitle(title: string | null, subtitle?: string): void
}
