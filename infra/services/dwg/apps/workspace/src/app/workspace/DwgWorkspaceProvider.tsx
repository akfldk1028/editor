import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { CadEditBatch } from "@dwg/contracts";

import { useProviderChat } from "../../features/agent-chat/useProviderChat";
import { useChangeReview } from "../../features/change-review/useChangeReview";
import { useDrawingIndex } from "../../features/drawing-explorer/useDrawingIndex";
import { useLayerVisibility } from "../../features/drawing-explorer/useLayerVisibility";
import type { DrawingSessionBarProps } from "../../features/drawing-sessions/DrawingSessionBar";
import { useDrawingSessions } from "../../features/drawing-sessions/useDrawingSessions";
import { useInspectionRun } from "../../features/inspection-results/useInspectionRun";
import { subscribeCadEditProposals } from "../../shared/cadEditProposalInbox";
import type { CadEntity, CadIndex } from "../../shared/types";

export type DwgSidebarTab = "project" | "sessions" | "skills";

/**
 * Everything the DWG sidebar, conversation and artifact share. Any frame (the
 * standalone app or a host shell) mounts this once around the three pieces.
 */
export interface DwgWorkspaceState {
  index: CadIndex | null;
  error: string | null;
  chat: ReturnType<typeof useProviderChat>;
  inspection: ReturnType<typeof useInspectionRun>;
  drawingSessionProps: DrawingSessionBarProps;
  changeReview: ReturnType<typeof useChangeReview>;
  layerVisibility: ReturnType<typeof useLayerVisibility>;
  selected: CadEntity | null;
  selectedHandle: string | null;
  setSelectedHandle(handle: string | null): void;
  highlightedHandles: ReadonlySet<string>;
  proposalError: string | null;
  sidebarTab: DwgSidebarTab;
  setSidebarTab(tab: DwgSidebarTab): void;
  sidebarQuery: string;
  setSidebarQuery(query: string): void;
  searchQuery: string;
  setSearchQuery(query: string): void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  gridVisible: boolean;
  setGridVisible(visible: boolean): void;
  runAgents(): Promise<void>;
  resetInspection(): void;
}

const DwgWorkspaceContext = createContext<DwgWorkspaceState | null>(null);

export function useDwgWorkspace() {
  const state = useContext(DwgWorkspaceContext);
  if (!state) throw new Error("useDwgWorkspace must be used inside <DwgWorkspaceProvider>");
  return state;
}

const sidebarTabKey = "dwg.sidebar-tab.v1";

function loadSidebarTab(): DwgSidebarTab {
  try {
    const value = window.localStorage.getItem(sidebarTabKey);
    return value === "sessions" || value === "skills" ? value : "project";
  } catch {
    return "project";
  }
}

export function DwgWorkspaceProvider({ children }: { children: ReactNode }) {
  const { index, error, refresh } = useDrawingIndex();
  const chat = useProviderChat();
  const inspection = useInspectionRun();
  const [selectedHandle, setSelectedHandle] = useState<string | null>(null);
  const [sidebarTab, setSidebarTabState] = useState<DwgSidebarTab>(loadSidebarTab);
  const [sidebarQuery, setSidebarQuery] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [gridVisible, setGridVisible] = useState(true);
  const searchRef = useRef<HTMLInputElement>(null);
  const [pendingChangeBatch, setPendingChangeBatch] = useState<CadEditBatch | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);
  // Switching the active drawing changes every read surface, so the workspace
  // reloads its index and drops a selection that belonged to the old drawing.
  const drawingSessions = useDrawingSessions(useCallback(() => {
    chat.reset();
    inspection.reset();
    setSelectedHandle(null);
    void refresh();
  }, [chat.reset, inspection.reset, refresh]));
  const refreshAfterMutation = useCallback(async () => {
    const refreshed = await refresh();
    if (!refreshed) return;
    setSelectedHandle((handle) => handle && refreshed.entities.some((entity) => entity.handle === handle) ? handle : null);
  }, [refresh]);
  const changeReview = useChangeReview(pendingChangeBatch, refreshAfterMutation);

  useEffect(() => subscribeCadEditProposals({
    onProposal: (batch) => {
      if (changeReview.isMutationInFlight()) {
        setProposalError("Finish the current CAD mutation before proposing another change.");
        return;
      }
      setProposalError(null);
      setPendingChangeBatch(batch);
    },
    onInvalid: () => setProposalError("Invalid CAD edit proposal.")
  }), [changeReview.isMutationInFlight]);

  const layerVisibility = useLayerVisibility(index?.layers ?? []);
  const selected = index?.entities.find((entity) => entity.handle === selectedHandle) ?? null;
  const highlightedHandles = useMemo(() => new Set(
    inspection.run?.findings.flatMap((finding) => finding.handle ? [finding.handle] : []) ?? []
  ), [inspection.run]);

  const setSidebarTab = useCallback((tab: DwgSidebarTab) => {
    setSidebarTabState(tab);
    try {
      window.localStorage.setItem(sidebarTabKey, tab);
    } catch {
      // Restricted storage keeps the tab for this runtime only.
    }
  }, []);

  const state: DwgWorkspaceState = {
    index,
    error,
    chat,
    inspection,
    drawingSessionProps: {
      busy: drawingSessions.busy,
      dialogAvailable: drawingSessions.dialogAvailable,
      error: drawingSessions.error,
      onActivate: drawingSessions.activate,
      onOpen: drawingSessions.open,
      sessions: drawingSessions.sessions
    },
    changeReview,
    layerVisibility,
    selected,
    selectedHandle,
    setSelectedHandle,
    highlightedHandles,
    proposalError,
    sidebarTab,
    setSidebarTab,
    sidebarQuery,
    setSidebarQuery,
    searchQuery,
    setSearchQuery,
    searchRef,
    gridVisible,
    setGridVisible,
    async runAgents() {
      setSelectedHandle(null);
      await inspection.start([{ kind: "layer", value: "0" }]);
    },
    resetInspection() {
      inspection.reset();
      setSelectedHandle(null);
    }
  };

  return <DwgWorkspaceContext.Provider value={state}>{children}</DwgWorkspaceContext.Provider>;
}
