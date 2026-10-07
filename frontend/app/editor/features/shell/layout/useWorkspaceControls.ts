import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type HTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent
} from "react";
import { flushSync } from "react-dom";

import {
  artifactPresentationFor,
  artifactShareFor,
  artifactWidthFor,
  clampArtifactWidth,
  clampSidebarWidth,
  layout,
  layoutModeFor,
  maximumArtifactWidth,
  sharedRowWidth
} from "./layoutModes";

export type NarrowPanel = "conversation" | "artifact";
/** How the sidebar is shown right now. */
export type SidebarPresentation = "inline" | "rail" | "drawer" | "hidden";

interface WorkspaceControlsOptions {
  /** Inline size of the workspace root, from its ResizeObserver. */
  workspaceWidth: number;
  preferredArtifactShare: number | null;
  preferredSidebarWidth: number;
  sidebarCollapsed: boolean;
  setPreferredArtifactShare(share: number): void;
  setPreferredSidebarWidth(width: number): void;
  setSidebarCollapsed(collapsed: boolean): void;
}

/** Runs a panel open/close inside a View Transition when the platform offers one and motion is allowed. */
function withViewTransition(update: () => void) {
  const reduceMotion = typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (typeof document.startViewTransition !== "function" || reduceMotion) {
    update();
    return;
  }
  // A second panel change while one animates skips the first; that is expected, not an error.
  document.startViewTransition(() => flushSync(update)).ready.catch(() => undefined);
}

export function useWorkspaceControls({
  workspaceWidth,
  preferredArtifactShare,
  preferredSidebarWidth,
  sidebarCollapsed,
  setPreferredArtifactShare,
  setPreferredSidebarWidth,
  setSidebarCollapsed
}: WorkspaceControlsOptions) {
  const mode = layoutModeFor(workspaceWidth);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [artifactOpen, setArtifactOpen] = useState(true);
  const [narrowPanel, setNarrowPanel] = useState<NarrowPanel>("conversation");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [artifactMaximized, setArtifactMaximized] = useState(false);
  const artifactDragStart = useRef<{ x: number; width: number } | null>(null);
  const sidebarDragStart = useRef<{ x: number; width: number } | null>(null);
  const activeResizeTarget = useRef<{ element: HTMLDivElement; pointerId: number } | null>(null);
  const removeResizeListeners = useRef<(() => void) | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const artifactButtonRef = useRef<HTMLButtonElement>(null);
  const topActionsRef = useRef<HTMLDivElement>(null);
  const previousMode = useRef(mode);

  const sidebarWidth = clampSidebarWidth(preferredSidebarWidth);
  const sidebarExpanded = !sidebarCollapsed;
  const sidebarPresentation: SidebarPresentation = mode === "wide"
    ? sidebarExpanded ? "inline" : "rail"
    : drawerOpen ? "drawer" : "hidden";
  const rowWidth = sharedRowWidth(workspaceWidth, mode, sidebarExpanded, sidebarWidth);
  const artifactPresentation = artifactPresentationFor(mode, rowWidth);
  const artifactWidth = artifactWidthFor(rowWidth, preferredArtifactShare);
  const artifactMaxWidth = maximumArtifactWidth(rowWidth);
  const artifactMinWidth = Math.min(layout.artifact.min, artifactMaxWidth);
  const artifactVisible = mode === "narrow" ? narrowPanel === "artifact" : artifactOpen;

  const latest = useRef({ rowWidth, setPreferredArtifactShare, setPreferredSidebarWidth });
  latest.current = { rowWidth, setPreferredArtifactShare, setPreferredSidebarWidth };

  // A mode change re-seats every panel: drawers and overlays close, narrow
  // starts on the conversation, and a maximized artifact is restored.
  useEffect(() => {
    if (previousMode.current === mode) return;
    previousMode.current = mode;
    setDrawerOpen(false);
    setNarrowPanel("conversation");
    setArtifactMaximized(false);
  }, [mode]);

  const finishResize = useCallback(() => {
    artifactDragStart.current = null;
    sidebarDragStart.current = null;
    const target = activeResizeTarget.current;
    activeResizeTarget.current = null;
    const removeListeners = removeResizeListeners.current;
    removeResizeListeners.current = null;
    removeListeners?.();
    document.body.classList.remove("resizing-artifact");
    document.body.classList.remove("resizing-sidebar");
    if (target?.element.hasPointerCapture(target.pointerId)) {
      try {
        target.element.releasePointerCapture(target.pointerId);
      } catch {
        // The browser may have already cancelled capture while unmounting.
      }
    }
  }, []);

  useEffect(() => finishResize, [finishResize]);

  const closeSidebar = useCallback(() => {
    withViewTransition(() => setDrawerOpen(false));
  }, []);

  const toggleSidebarFromMenu = useCallback(() => {
    withViewTransition(() => {
      if (mode === "wide") setSidebarCollapsed(!sidebarCollapsed);
      else setDrawerOpen((open) => !open);
    });
  }, [mode, setSidebarCollapsed, sidebarCollapsed]);

  const setSidebarExpanded = useCallback((expanded: boolean) => {
    withViewTransition(() => setSidebarCollapsed(!expanded));
  }, [setSidebarCollapsed]);

  const openArtifact = useCallback(() => {
    withViewTransition(() => {
      if (mode === "narrow") setNarrowPanel("artifact");
      else setArtifactOpen(true);
    });
  }, [mode]);

  const closeArtifact = useCallback(() => {
    withViewTransition(() => {
      setArtifactMaximized(false);
      if (mode === "narrow") setNarrowPanel("conversation");
      else setArtifactOpen(false);
    });
  }, [mode]);

  const showNarrowPanel = useCallback((panel: NarrowPanel) => {
    withViewTransition(() => setNarrowPanel(panel));
  }, []);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSettingsOpen(false);
        setArtifactMaximized(false);
      }
    };
    const pointerdown = (event: PointerEvent) => {
      if (!topActionsRef.current?.contains(event.target as Node)) {
        setSettingsOpen(false);
      }
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("pointerdown", pointerdown);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("pointerdown", pointerdown);
    };
  }, []);

  function setArtifactWidth(width: number) {
    setPreferredArtifactShare(artifactShareFor(rowWidth, clampArtifactWidth(rowWidth, width)));
  }

  function setSidebarWidth(width: number) {
    setPreferredSidebarWidth(clampSidebarWidth(width));
  }

  function startResize(
    event: ReactPointerEvent<HTMLDivElement>,
    bodyClass: "resizing-artifact" | "resizing-sidebar"
  ) {
    const element = event.currentTarget;
    const pointerId = event.pointerId;
    activeResizeTarget.current = { element, pointerId };

    const move = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== pointerId) return;
      const current = latest.current;
      if (artifactDragStart.current) {
        current.setPreferredArtifactShare(artifactShareFor(current.rowWidth, clampArtifactWidth(
          current.rowWidth,
          artifactDragStart.current.width + artifactDragStart.current.x - pointerEvent.clientX
        )));
      }
      if (sidebarDragStart.current) {
        current.setPreferredSidebarWidth(clampSidebarWidth(
          sidebarDragStart.current.width + pointerEvent.clientX - sidebarDragStart.current.x
        ));
      }
    };
    const finishPointer = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === pointerId) finishResize();
    };
    const finishOnBlur = () => finishResize();

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finishPointer);
    window.addEventListener("pointercancel", finishPointer);
    window.addEventListener("blur", finishOnBlur);
    element.addEventListener("lostpointercapture", finishPointer);
    removeResizeListeners.current = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finishPointer);
      window.removeEventListener("pointercancel", finishPointer);
      window.removeEventListener("blur", finishOnBlur);
      element.removeEventListener("lostpointercapture", finishPointer);
    };
    document.body.classList.add(bodyClass);
    try {
      element.setPointerCapture(pointerId);
    } catch {
      finishResize();
    }
  }

  /** Pointer and keyboard props for a `role="separator"` between two panels. */
  const sidebarSeparatorProps: HTMLAttributes<HTMLDivElement> = {
    "aria-label": "Sidebar width",
    "aria-orientation": "vertical",
    "aria-valuemax": layout.sidebar.max,
    "aria-valuemin": layout.sidebar.min,
    "aria-valuenow": Math.round(sidebarWidth),
    role: "separator",
    tabIndex: 0,
    onPointerDown(event) {
      finishResize();
      sidebarDragStart.current = { x: event.clientX, width: sidebarWidth };
      startResize(event, "resizing-sidebar");
    },
    onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
      const next = {
        ArrowLeft: sidebarWidth - layout.resizeStep,
        ArrowRight: sidebarWidth + layout.resizeStep,
        Home: layout.sidebar.min,
        End: layout.sidebar.max
      }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      setSidebarWidth(next);
    }
  };

  const artifactSeparatorProps: HTMLAttributes<HTMLDivElement> = {
    "aria-label": "아티팩트 너비 조절",
    "aria-orientation": "vertical",
    "aria-valuemax": artifactMaxWidth,
    "aria-valuemin": artifactMinWidth,
    "aria-valuenow": artifactWidth,
    role: "separator",
    tabIndex: 0,
    onPointerDown(event) {
      finishResize();
      artifactDragStart.current = { x: event.clientX, width: artifactWidth };
      startResize(event, "resizing-artifact");
    },
    onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
      // The artifact grows leftwards, so ArrowLeft widens it.
      const next = {
        ArrowLeft: artifactWidth + layout.resizeStep,
        ArrowRight: artifactWidth - layout.resizeStep,
        Home: artifactMinWidth,
        End: artifactMaxWidth
      }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      setArtifactWidth(next);
    }
  };

  return {
    mode,
    artifactMaximized,
    artifactPresentation,
    artifactVisible,
    artifactWidth,
    narrowPanel,
    menuButtonRef,
    artifactButtonRef,
    sidebarPresentation,
    sidebarWidth,
    settingsOpen,
    topActionsRef,
    artifactSeparatorProps,
    sidebarSeparatorProps,
    closeSidebar,
    closeArtifact,
    openArtifact,
    setArtifactMaximized,
    setSettingsOpen,
    setSidebarExpanded,
    showNarrowPanel,
    toggleSidebarFromMenu
  };
}
