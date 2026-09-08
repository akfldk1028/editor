import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent
} from "react";

import { clampArtifactWidth, clampSidebarWidth } from "./workspacePreferences";

const compactArtifactBreakpoint = 886;
const desktopSidebarBreakpoint = 1280;

interface WorkspaceControlsOptions {
  preferredArtifactWidth: number;
  preferredSidebarWidth: number;
  setPreferredArtifactWidth(width: number): void;
  setPreferredSidebarWidth(width: number): void;
}

export function useWorkspaceControls({
  preferredArtifactWidth,
  preferredSidebarWidth,
  setPreferredArtifactWidth,
  setPreferredSidebarWidth
}: WorkspaceControlsOptions) {
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.innerWidth >= desktopSidebarBreakpoint
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [gridVisible, setGridVisible] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [artifactMaximized, setArtifactMaximized] = useState(false);
  const [artifactOpen, setArtifactOpen] = useState(
    () => window.innerWidth > compactArtifactBreakpoint
  );
  const artifactDragStart = useRef<{ x: number; width: number } | null>(null);
  const sidebarDragStart = useRef<{ x: number; width: number } | null>(null);
  const artifactOpenRef = useRef(artifactOpen);
  const sidebarOpenRef = useRef(sidebarOpen);
  const activeResizeTarget = useRef<{
    element: HTMLDivElement;
    pointerId: number;
  } | null>(null);
  const removeResizeListeners = useRef<(() => void) | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const artifactButtonRef = useRef<HTMLButtonElement>(null);
  const topActionsRef = useRef<HTMLDivElement>(null);
  const setPreferredArtifactWidthRef = useRef(setPreferredArtifactWidth);
  const setPreferredSidebarWidthRef = useRef(setPreferredSidebarWidth);
  const desktop = viewportWidth >= desktopSidebarBreakpoint;
  const artifactOverlay = viewportWidth <= compactArtifactBreakpoint;
  const sidebarWidth = clampSidebarWidth(preferredSidebarWidth);
  const artifactWidth = clampArtifactWidth(
    viewportWidth,
    preferredArtifactWidth,
    desktop,
    sidebarWidth
  );
  artifactOpenRef.current = artifactOpen;
  sidebarOpenRef.current = sidebarOpen;

  useEffect(() => {
    setPreferredArtifactWidthRef.current = setPreferredArtifactWidth;
  }, [setPreferredArtifactWidth]);

  useEffect(() => {
    setPreferredSidebarWidthRef.current = setPreferredSidebarWidth;
  }, [setPreferredSidebarWidth]);

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
    setSidebarOpen(false);
  }, []);

  const toggleSidebarFromMenu = useCallback(() => {
    setSidebarOpen((open) => {
      if (!open && window.innerWidth <= compactArtifactBreakpoint) setArtifactOpen(false);
      return !open;
    });
  }, []);

  const openArtifact = useCallback(() => {
    if (window.innerWidth <= compactArtifactBreakpoint) setSidebarOpen(false);
    setArtifactOpen(true);
  }, []);

  const closeArtifact = useCallback(() => {
    setArtifactMaximized(false);
    setArtifactOpen(false);
  }, []);

  useEffect(() => {
    const resize = () => {
      const width = window.innerWidth;
      if (
        width <= compactArtifactBreakpoint &&
        artifactOpenRef.current &&
        sidebarOpenRef.current
      ) {
        sidebarOpenRef.current = false;
        setSidebarOpen(false);
      }
      setViewportWidth(width);
      if (width >= desktopSidebarBreakpoint) {
        sidebarOpenRef.current = true;
        setSidebarOpen(true);
      }
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
      if (event.key === "Escape") {
        setSettingsOpen(false);
        setNotificationsOpen(false);
        setArtifactMaximized(false);
        if (!desktop && sidebarOpen) closeSidebar();
      }
    };
    const pointerdown = (event: PointerEvent) => {
      if (!topActionsRef.current?.contains(event.target as Node)) {
        setSettingsOpen(false);
        setNotificationsOpen(false);
      }
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("pointerdown", pointerdown);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("pointerdown", pointerdown);
    };
  }, [closeSidebar, desktop, sidebarOpen]);

  function resizeArtifactBy(delta: number) {
    setPreferredArtifactWidth(clampArtifactWidth(
      viewportWidth,
      artifactWidth + delta,
      desktop,
      sidebarWidth
    ));
  }

  function resizeSidebarBy(delta: number) {
    setPreferredSidebarWidth(clampSidebarWidth(sidebarWidth + delta));
  }

  function startArtifactResize(event: ReactPointerEvent<HTMLDivElement>) {
    finishResize();
    artifactDragStart.current = { x: event.clientX, width: artifactWidth };
    startResize(event, "resizing-artifact");
  }

  function startSidebarResize(event: ReactPointerEvent<HTMLDivElement>) {
    finishResize();
    sidebarDragStart.current = { x: event.clientX, width: sidebarWidth };
    startResize(event, "resizing-sidebar");
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
      if (artifactDragStart.current) {
        setPreferredArtifactWidthRef.current(clampArtifactWidth(
          window.innerWidth,
          artifactDragStart.current.width + artifactDragStart.current.x - pointerEvent.clientX,
          window.innerWidth >= desktopSidebarBreakpoint,
          sidebarWidth
        ));
      }
      if (sidebarDragStart.current) {
        setPreferredSidebarWidthRef.current(clampSidebarWidth(
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

  return {
    artifactMaximized,
    artifactOverlay,
    artifactOpen,
    artifactWidth,
    desktop,
    gridVisible,
    notificationsOpen,
    searchQuery,
    searchRef,
    menuButtonRef,
    artifactButtonRef,
    sidebarWidth,
    settingsOpen,
    sidebarOpen,
    topActionsRef,
    closeSidebar,
    closeArtifact,
    openArtifact,
    resizeArtifactBy,
    resizeSidebarBy,
    setArtifactMaximized,
    setArtifactOpen,
    setGridVisible,
    setNotificationsOpen,
    setSearchQuery,
    setSettingsOpen,
    startArtifactResize,
    startSidebarResize,
    toggleSidebarFromMenu
  };
}
