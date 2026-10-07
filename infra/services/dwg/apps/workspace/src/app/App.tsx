import {
  Menu,
  MessageSquare,
  PanelRight,
  Settings2,
  SquarePen,
  View
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AgentWorkspace, ConversationHeading } from "../features/agent-chat/AgentWorkspace";
import { useProviderChat } from "../features/agent-chat/useProviderChat";
import { useChangeReview } from "../features/change-review/useChangeReview";
import { useDrawingIndex } from "../features/drawing-explorer/useDrawingIndex";
import { useLayerVisibility } from "../features/drawing-explorer/useLayerVisibility";
import { DrawingSessionBar, OpenDrawingButton } from "../features/drawing-sessions/DrawingSessionBar";
import { useDrawingSessions } from "../features/drawing-sessions/useDrawingSessions";
import { useInspectionRun } from "../features/inspection-results/useInspectionRun";
import { subscribeCadEditProposals } from "../shared/cadEditProposalInbox";
import type { CadEditBatch } from "@dwg/contracts";
import { CadArtifactPanel } from "./CadArtifactPanel";
import { layout } from "./layoutModes";
import { useElementInlineSize } from "./useElementInlineSize";
import { useWorkspaceControls } from "./useWorkspaceControls";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import type { ThemePreference } from "./workspacePreferences";
import { useWorkspacePreferences } from "./useWorkspacePreferences";
import "./styles.css";

export function App() {
  const rootRef = useRef<HTMLDivElement>(null);
  const workspaceWidth = useElementInlineSize(rootRef);
  return <div className="dwg-workspace" ref={rootRef}><WorkspaceContent workspaceWidth={workspaceWidth} /></div>;
}

/** Layout numbers reach CSS only through these properties (see layoutModes.ts). */
const layoutProperties = {
  "--rail-width": `${layout.sidebar.rail}px`,
  "--separator": `${layout.separatorWidth}px`,
  "--conversation-min": `${layout.conversationMinWidth}px`,
  "--artifact-min": `${layout.artifact.min}px`,
  "--drawer-max": `${layout.drawerMaxWidth}px`
};

function WorkspaceContent({ workspaceWidth }: { workspaceWidth: number }) {
  const { index, error, refresh } = useDrawingIndex();
  const chat = useProviderChat();
  const inspection = useInspectionRun();
  const workspace = useWorkspacePreferences();
  const controls = useWorkspaceControls({
    workspaceWidth,
    preferredArtifactShare: workspace.preferences.artifactShare,
    preferredSidebarWidth: workspace.preferences.sidebarWidth,
    sidebarCollapsed: workspace.preferences.sidebarCollapsed,
    setPreferredArtifactShare: workspace.setArtifactShare,
    setPreferredSidebarWidth: workspace.setSidebarWidth,
    setSidebarCollapsed: workspace.setSidebarCollapsed
  });
  const {
    mode,
    artifactMaximized,
    artifactPresentation,
    artifactVisible,
    artifactWidth,
    gridVisible,
    narrowPanel,
    searchQuery,
    searchRef,
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
    setGridVisible,
    setSearchQuery,
    setSettingsOpen,
    setSidebarExpanded,
    showNarrowPanel,
    toggleSidebarFromMenu
  } = controls;
  const [selectedHandle, setSelectedHandle] = useState<string | null>(null);
  const [sidebarQuery, setSidebarQuery] = useState("");
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

  const layerVisibility = useLayerVisibility(
    index?.layers ?? []
  );
  const selected = index?.entities.find((entity) => entity.handle === selectedHandle) ?? null;
  const highlightedHandles = useMemo(() => new Set(
    inspection.run?.findings.flatMap((finding) => finding.handle ? [finding.handle] : []) ?? []
  ), [inspection.run]);

  async function runAgents() {
    setSelectedHandle(null);
    await inspection.start([{ kind: "layer", value: "0" }]);
  }

  if (error) {
    return <div className="load-state error-state">DWG 인덱스를 불러오지 못했습니다. {error}</div>;
  }
  if (!index) {
    return <div className="load-state"><span className="loading-mark" /> 로컬 DWG 인덱스를 불러오는 중</div>;
  }

  const drawingSessionProps = {
    busy: drawingSessions.busy,
    dialogAvailable: drawingSessions.dialogAvailable,
    error: drawingSessions.error,
    onActivate: drawingSessions.activate,
    onOpen: drawingSessions.open,
    sessions: drawingSessions.sessions
  };

  return (
    <div className="app-shell" data-layout={mode} data-theme={workspace.resolvedTheme} style={layoutProperties as React.CSSProperties}>
      <div
        className="workspace-grid"
        data-artifact={artifactVisible ? artifactPresentation : "closed"}
        data-maximized={artifactMaximized && artifactVisible && artifactPresentation !== "panel"}
        data-narrow-panel={narrowPanel}
        data-sidebar={sidebarPresentation}
        style={{
          "--artifact-width": `${artifactWidth}px`,
          "--sidebar-width": `${sidebarWidth}px`
        } as React.CSSProperties}
      >
        {sidebarPresentation !== "hidden" && (
          <WorkspaceSidebar
            activeSessionId={chat.activeSessionId}
            drawingSessions={<DrawingSessionBar {...drawingSessionProps} />}
            headingActions={<OpenDrawingButton {...drawingSessionProps} />}
            hiddenLayers={layerVisibility.hiddenLayers}
            index={index}
            onClose={closeSidebar}
            onExpandedChange={setSidebarExpanded}
            onNewSession={chat.reset}
            onQueryChange={setSidebarQuery}
            onSelectSession={chat.selectSession}
            onSelectTab={workspace.setSidebarTab}
            onToggleLayer={layerVisibility.toggleLayer}
            presentation={sidebarPresentation}
            query={sidebarQuery}
            restoreFocusRef={menuButtonRef}
            sessions={chat.sessions}
            tab={workspace.preferences.sidebarTab}
          />
        )}
        {sidebarPresentation === "drawer" && <button aria-label="탐색 닫기" className="scrim sidebar-scrim" onClick={closeSidebar} tabIndex={-1} />}
        {sidebarPresentation === "inline" && <div className="sidebar-resizer" {...sidebarSeparatorProps} />}

        <header className="topbar" data-modal-background>
          {mode !== "wide" && (
            <button
              aria-expanded={sidebarPresentation === "drawer"}
              aria-label="탐색 열기"
              className="icon-button menu-button"
              onClick={toggleSidebarFromMenu}
              ref={menuButtonRef}
              title="탐색"
            >
              <Menu size={18} />
            </button>
          )}
          <ConversationHeading activeSession={chat.activeSession} drawingDisplayName={index.source.displayName} />
          {mode === "narrow" && (
            <div aria-label="패널 전환" className="panel-switch" role="group">
              <button aria-pressed={narrowPanel === "conversation"} onClick={() => showNarrowPanel("conversation")} type="button">
                <MessageSquare aria-hidden="true" size={14} /><span>대화</span>
              </button>
              <button aria-pressed={narrowPanel === "artifact"} onClick={() => showNarrowPanel("artifact")} ref={artifactButtonRef} type="button">
                <View aria-hidden="true" size={14} /><span>도면</span>
              </button>
            </div>
          )}
          <div className="topbar-actions" ref={topActionsRef}>
            <button aria-label="새 대화" className="icon-button" onClick={chat.reset} title="새 대화">
              <SquarePen size={17} />
            </button>
            {mode !== "narrow" && !artifactVisible && (
              <button
                aria-label="CAD 아티팩트 열기"
                className="icon-button artifact-toggle"
                onClick={openArtifact}
                ref={artifactButtonRef}
                title="CAD 아티팩트 열기"
              >
                <PanelRight size={17} />
              </button>
            )}
            <div className="settings-anchor">
              <button
                aria-expanded={settingsOpen}
                aria-label="설정"
                className="icon-button"
                onClick={() => setSettingsOpen((open) => !open)}
                title="설정 · 알림"
              >
                <Settings2 size={17} />
              </button>
              {settingsOpen && (
                <div className="settings-popover" role="dialog" aria-label="뷰어 설정">
                  <label>
                    <span>테마</span>
                    <select
                      aria-label="테마"
                      onChange={(event) => workspace.setTheme(event.target.value as ThemePreference)}
                      value={workspace.preferences.theme}
                    >
                      <option value="system">System</option>
                      <option value="light">Light</option>
                      <option value="dark">Dark</option>
                    </select>
                  </label>
                  <label><span>CAD grid</span><input checked={gridVisible} onChange={(event) => setGridVisible(event.target.checked)} type="checkbox" /></label>
                  <div className="settings-notifications">
                    <span>알림</span>
                    <p className="notification-popover" role="status">새 알림이 없습니다.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        <AgentWorkspace
          activeSession={chat.activeSession}
          chatError={chat.error}
          chatLoading={chat.loading}
          chatResult={chat.result}
          inspectionError={inspection.error}
          inspectionLoading={inspection.loading}
          inspectionRun={inspection.run}
          message={chat.message}
          onCancel={chat.cancel}
          onMessageChange={chat.setMessage}
          onProviderChange={chat.setSelectedProvider}
          onSubmit={chat.submit}
          providers={chat.providers}
          selectedProvider={chat.selectedProvider}
        />

        {artifactVisible && (
          <>
            {artifactPresentation === "inline" && <div className="artifact-resizer" {...artifactSeparatorProps} />}
            {artifactPresentation === "sheet" && <button aria-label="아티팩트 배경 닫기" className="scrim artifact-scrim" onClick={closeArtifact} tabIndex={-1} />}
            <CadArtifactPanel
              changeReview={changeReview}
              gridVisible={gridVisible}
              hiddenLayers={layerVisibility.hiddenLayers}
              highlightedHandles={highlightedHandles}
              index={index}
              inspectionLoading={inspection.loading}
              maximized={artifactMaximized}
              presentation={artifactPresentation}
              restoreFocusRef={artifactButtonRef}
              onClose={closeArtifact}
              onGridVisibleChange={setGridVisible}
              onMaximizedChange={setArtifactMaximized}
              onResetInspection={() => {
                inspection.reset();
                setSelectedHandle(null);
              }}
              onRunAgents={() => void runAgents()}
              onSearchQueryChange={setSearchQuery}
              onSelectFinding={setSelectedHandle}
              run={inspection.run}
              searchInputRef={searchRef}
              searchQuery={searchQuery}
              selected={selected}
              selectedHandle={selectedHandle}
              proposalError={proposalError}
            />
          </>
        )}
      </div>
    </div>
  );
}
