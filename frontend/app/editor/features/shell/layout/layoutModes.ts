/**
 * Single source of the workspace layout numbers. The CSS container queries in
 * styles.css repeat the two mode thresholds as literals (container query
 * conditions cannot read custom properties); tests/unit/layout-modes.test.ts
 * fails when the two drift apart. Every other size reaches CSS as a custom
 * property written from these constants.
 */
export const layout = {
  /** Workspace inline size at which the sidebar sits inline (wide mode). */
  wideMinWidth: 1200,
  /** Workspace inline size at which two panels may share the row (medium mode). */
  mediumMinWidth: 768,
  sidebar: { default: 240, min: 200, max: 320, rail: 56 },
  drawerMaxWidth: 320,
  conversationMinWidth: 320,
  artifact: { min: 360, defaultShare: 0.45, minShare: 0.2, maxShare: 0.8 },
  separatorWidth: 7,
  resizeStep: 16
} as const;

export type LayoutMode = "wide" | "medium" | "narrow";
export type ArtifactPresentation = "inline" | "sheet" | "panel";

export function layoutModeFor(workspaceWidth: number): LayoutMode {
  if (workspaceWidth >= layout.wideMinWidth) return "wide";
  if (workspaceWidth >= layout.mediumMinWidth) return "medium";
  return "narrow";
}

/** Width taken by an inline sidebar (panel + its separator, or the rail). */
export function sidebarTrackWidth(mode: LayoutMode, expanded: boolean, sidebarWidth: number) {
  if (mode !== "wide") return 0;
  return expanded ? sidebarWidth + layout.separatorWidth : layout.sidebar.rail;
}

/** Width the conversation and artifact share once the sidebar track is removed. */
export function sharedRowWidth(workspaceWidth: number, mode: LayoutMode, sidebarExpanded: boolean, sidebarWidth: number) {
  return Math.max(0, workspaceWidth - sidebarTrackWidth(mode, sidebarExpanded, sidebarWidth));
}

/** Largest artifact that still leaves the conversation its minimum. */
export function maximumArtifactWidth(rowWidth: number) {
  return Math.max(0, rowWidth - layout.separatorWidth - layout.conversationMinWidth);
}

export function clampArtifactShare(share: number) {
  return Math.min(layout.artifact.maxShare, Math.max(layout.artifact.minShare, share));
}

/**
 * The artifact width for a preferred share of the row (null = default share).
 * The minimum yields to the maximum so the conversation always keeps its floor.
 */
export function artifactWidthFor(rowWidth: number, share: number | null) {
  return clampArtifactWidth(rowWidth, rowWidth * (share ?? layout.artifact.defaultShare));
}

/** Clamps a px width into [artifact minimum, row maximum]. */
export function clampArtifactWidth(rowWidth: number, desiredWidth: number) {
  const maximum = maximumArtifactWidth(rowWidth);
  const minimum = Math.min(layout.artifact.min, maximum);
  return Math.round(Math.min(maximum, Math.max(minimum, desiredWidth)));
}

/** The share a px width represents, for persisting a resize. */
export function artifactShareFor(rowWidth: number, width: number) {
  return rowWidth > 0 ? clampArtifactShare(width / rowWidth) : layout.artifact.defaultShare;
}

export function clampSidebarWidth(desiredWidth: number) {
  return Math.min(layout.sidebar.max, Math.max(layout.sidebar.min, desiredWidth));
}

/**
 * Narrow shows one panel at a time; otherwise the artifact sits beside the
 * conversation only while both minimums fit, else it overlays as a sheet.
 */
export function artifactPresentationFor(mode: LayoutMode, rowWidth: number): ArtifactPresentation {
  if (mode === "narrow") return "panel";
  return maximumArtifactWidth(rowWidth) >= layout.artifact.min ? "inline" : "sheet";
}
