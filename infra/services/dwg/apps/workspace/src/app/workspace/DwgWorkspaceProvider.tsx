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

type ProviderChat = ReturnType<typeof useProviderChat>;
/** The composer's text changes on every keystroke, so it has its own context (`useDwgChatInput`). */
export type DwgChatInput = Pick<ProviderChat, "message" | "setMessage">;

/**
 * Everything the DWG sidebar, conversation and artifact share. Any frame (the
 * standalone app or a host shell) mounts this once around the three pieces.
 */
export interface DwgWorkspaceState {
  index: CadIndex | null;
  error: string | null;
  chat: Omit<ProviderChat, "message" | "setMessage">;
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
const DwgChatInputContext = createContext<DwgChatInput | null>(null);

export function useDwgWorkspace() {
  const state = useContext(DwgWorkspaceContext);
  if (!state) throw new Error("useDwgWorkspace must be used inside <DwgWorkspaceProvider>");
  return state;
}

/** The composer's text; only the composer re-renders while typing. */
export function useDwgChatInput() {
  const input = useContext(DwgChatInputContext);
  if (!input) throw new Error("useDwgChatInput must be used inside <DwgWorkspaceProvider>");
  return input;
}

/**
 * The same object while its data fields are unchanged (by identity); its functions are stable
 * and always call the newest version. Lets the hooks' fresh return objects feed a memoized context.
 */
function useSteady<T extends object>(value: T): T {
  const latest = useRef(value);
  latest.current = value;
  const trampolines = useRef(new Map<string, (...args: unknown[]) => unknown>());
  const cache = useRef<{ keys: string[]; data: unknown[]; object: T } | null>(null);
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  const data = keys.map((key) => typeof record[key] === "function" ? null : record[key]);
  const previous = cache.current;
  if (previous && previous.keys.length === keys.length && previous.keys.every((key, i) => key === keys[i])
    && previous.data.every((item, i) => Object.is(item, data[i]))) return previous.object;
  const object: Record<string, unknown> = {};
  for (const key of keys) {
    if (typeof record[key] !== "function") {
      object[key] = record[key];
      continue;
    }
    let call = trampolines.current.get(key);
    if (!call) {
      call = (...args: unknown[]) => (latest.current as Record<string, (...args: unknown[]) => unknown>)[key]!(...args);
      trampolines.current.set(key, call);
    }
    object[key] = call;
  }
  cache.current = { keys, data, object: object as T };
  return object as T;
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
  const providerChat = useProviderChat();
  const inspection = useSteady(useInspectionRun());
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
  const { message, setMessage, ...chatRest } = providerChat;
  // `activeSession` is read from the store on every render; it only changes with these two.
  const activeSession = useMemo(() => providerChat.activeSession, [providerChat.activeSessionId, providerChat.sessions]);
  const chat = useSteady({ ...chatRest, activeSession });
  const chatInput = useMemo<DwgChatInput>(() => ({ message, setMessage }), [message, setMessage]);
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
  const changeReview = useSteady(useChangeReview(pendingChangeBatch, refreshAfterMutation));

  useEffect(() => subscribeCadEditProposals({
    onProposal: (batch) => {
      if (changeReview.isMutationInFlight()) {
        setProposalError("진행 중인 도면 변경을 마친 뒤 다음 변경을 제안해 주세요.");
        return;
      }
      setProposalError(null);
      setPendingChangeBatch(batch);
    },
    onInvalid: () => setProposalError("도면 변경 제안의 형식이 올바르지 않습니다.")
  }), [changeReview.isMutationInFlight]);

  const layerVisibility = useSteady(useLayerVisibility(index?.layers ?? []));
  const selected = useMemo(() => index?.entities.find((entity) => entity.handle === selectedHandle) ?? null, [index, selectedHandle]);
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

  const drawingSessionProps = useSteady<DrawingSessionBarProps>({
    busy: drawingSessions.busy,
    dialogAvailable: drawingSessions.dialogAvailable,
    error: drawingSessions.error,
    onActivate: drawingSessions.activate,
    onOpen: drawingSessions.open,
    sessions: drawingSessions.sessions
  });
  const runAgents = useCallback(async () => {
    setSelectedHandle(null);
    await inspection.start([{ kind: "layer", value: "0" }]);
  }, [inspection.start]);
  const resetInspection = useCallback(() => {
    inspection.reset();
    setSelectedHandle(null);
  }, [inspection.reset]);

  // Memoized: typing in the composer (its own context) leaves the CAD viewer and sidebar alone.
  const state = useMemo<DwgWorkspaceState>(() => ({
    index,
    error,
    chat,
    inspection,
    drawingSessionProps,
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
    runAgents,
    resetInspection
  }), [index, error, chat, inspection, drawingSessionProps, changeReview, layerVisibility, selected, selectedHandle,
    highlightedHandles, proposalError, sidebarTab, setSidebarTab, sidebarQuery, searchQuery, gridVisible, runAgents, resetInspection]);

  return (
    <DwgWorkspaceContext.Provider value={state}>
      <DwgChatInputContext.Provider value={chatInput}>{children}</DwgChatInputContext.Provider>
    </DwgWorkspaceContext.Provider>
  );
}
