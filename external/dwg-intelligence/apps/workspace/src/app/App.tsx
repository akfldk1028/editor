import {
  Bell,
  Menu,
  PanelRight,
  Settings2
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentWorkspace } from "../features/agent-chat/AgentWorkspace";
import { useProviderChat } from "../features/agent-chat/useProviderChat";
import { useChangeReview } from "../features/change-review/useChangeReview";
import { useDrawingIndex } from "../features/drawing-explorer/useDrawingIndex";
import { useLayerVisibility } from "../features/drawing-explorer/useLayerVisibility";
import { DrawingSessionBar } from "../features/drawing-sessions/DrawingSessionBar";
import { useDrawingSessions } from "../features/drawing-sessions/useDrawingSessions";
import { useInspectionRun } from "../features/inspection-results/useInspectionRun";
import { subscribeCadEditProposals } from "../shared/cadEditProposalInbox";
import type { CadEditBatch } from "@dwg/contracts";
import { CadArtifactPanel } from "./CadArtifactPanel";
import { useWorkspaceControls } from "./useWorkspaceControls";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import type { ThemePreference } from "./workspacePreferences";
import { useWorkspacePreferences } from "./useWorkspacePreferences";
import "./styles.css";

export function App() {
  const { index, error, refresh } = useDrawingIndex();
  const chat = useProviderChat();
  const inspection = useInspectionRun();
  const workspace = useWorkspacePreferences();
  const {
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
  } = useWorkspaceControls({
    preferredArtifactWidth: workspace.preferences.artifactWidth,
    preferredSidebarWidth: workspace.preferences.sidebarWidth,
    setPreferredArtifactWidth: workspace.setArtifactWidth,
    setPreferredSidebarWidth: workspace.setSidebarWidth
  });
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

  return (
    <div className="app-shell" data-theme={workspace.resolvedTheme}>
      <header className="topbar" data-modal-background>
        <button
          aria-label="탐색 열기"
          className="icon-button menu-button"
          onClick={toggleSidebarFromMenu}
          ref={menuButtonRef}
        >
          <Menu size={17} />
        </button>
        <div className="file-context">
          <strong>Drawing review</strong>
          <span>Local CAD workspace</span>
        </div>
        {!artifactOpen && (
          <button
            aria-label="CAD 아티팩트 열기"
            className="icon-button artifact-toggle"
            onClick={openArtifact}
            ref={artifactButtonRef}
          >
            <PanelRight size={15} />
          </button>
        )}
        <div className="topbar-actions" ref={topActionsRef}>
          <div className="settings-anchor">
            <button className="icon-button" aria-label="알림" onClick={() => setNotificationsOpen((open) => !open)}><Bell size={15} /></button>
            {notificationsOpen && <div className="notification-popover" role="status">새 알림이 없습니다.</div>}
          </div>
          <div className="settings-anchor">
            <button
              aria-expanded={settingsOpen}
              aria-label="설정"
              className="icon-button"
              onClick={() => setSettingsOpen((open) => !open)}
            >
              <Settings2 size={15} />
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
                <label><input checked={gridVisible} onChange={(event) => setGridVisible(event.target.checked)} type="checkbox" /> CAD grid</label>
              </div>
            )}
          </div>
        </div>
      </header>

      <div
        className={`workspace-grid ${artifactMaximized ? "artifact-maximized" : ""} ${artifactOpen ? "" : "artifact-closed"}`}
        style={{
          "--artifact-width": `${artifactWidth}px`,
          "--sidebar-width": `${sidebarWidth}px`
        } as React.CSSProperties}
      >
        {sidebarOpen && (
          <WorkspaceSidebar
            activeSessionId={chat.activeSessionId}
            drawingSessions={(
              <DrawingSessionBar
                busy={drawingSessions.busy}
                dialogAvailable={drawingSessions.dialogAvailable}
                error={drawingSessions.error}
                onActivate={drawingSessions.activate}
                onOpen={drawingSessions.open}
                sessions={drawingSessions.sessions}
              />
            )}
            hiddenLayers={layerVisibility.hiddenLayers}
            index={index}
            onClose={closeSidebar}
            onNewSession={chat.reset}
            onQueryChange={setSidebarQuery}
            onSelectSession={chat.selectSession}
            onSelectTab={workspace.setSidebarTab}
            onToggleLayer={layerVisibility.toggleLayer}
            overlay={!desktop}
            query={sidebarQuery}
            restoreFocusRef={menuButtonRef}
            sessions={chat.sessions}
            tab={workspace.preferences.sidebarTab}
          />
        )}
        {!desktop && sidebarOpen && <button aria-label="탐색 닫기" className="sidebar-scrim" onClick={closeSidebar} />}

        {desktop && sidebarOpen && (
          <div
            aria-label="Sidebar width"
            aria-orientation="vertical"
            aria-valuemax={420}
            aria-valuemin={280}
            aria-valuenow={Math.round(sidebarWidth)}
            className="sidebar-resizer"
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                resizeSidebarBy(-16);
              } else if (event.key === "ArrowRight") {
                event.preventDefault();
                resizeSidebarBy(16);
              } else if (event.key === "Home") {
                event.preventDefault();
                resizeSidebarBy(280 - sidebarWidth);
              } else if (event.key === "End") {
                event.preventDefault();
                resizeSidebarBy(420 - sidebarWidth);
              }
            }}
            onPointerDown={startSidebarResize}
            role="separator"
            tabIndex={0}
          />
        )}

        <AgentWorkspace
          activeSession={chat.activeSession}
          chatError={chat.error}
          chatLoading={chat.loading}
          chatResult={chat.result}
          drawingDisplayName={index.source.displayName}
          inspectionError={inspection.error}
          inspectionLoading={inspection.loading}
          inspectionRun={inspection.run}
          message={chat.message}
          onCancel={chat.cancel}
          onMessageChange={chat.setMessage}
          onNewChat={chat.reset}
          onProviderChange={chat.setSelectedProvider}
          onSubmit={chat.submit}
          providers={chat.providers}
          selectedProvider={chat.selectedProvider}
        />

        {artifactOpen && (
          <>
            <div
              aria-label="CAD 아티팩트 너비 조절"
              aria-orientation="vertical"
              aria-valuemax={1200}
              aria-valuemin={520}
              aria-valuenow={Math.round(artifactWidth)}
              className="artifact-resizer"
              onKeyDown={(event) => {
                if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                event.preventDefault();
                resizeArtifactBy(event.key === "ArrowLeft" ? 32 : -32);
              }}
              onPointerDown={startArtifactResize}
              role="separator"
              tabIndex={0}
            />

            <CadArtifactPanel
              changeReview={changeReview}
              gridVisible={gridVisible}
              hiddenLayers={layerVisibility.hiddenLayers}
              highlightedHandles={highlightedHandles}
              index={index}
              inspectionLoading={inspection.loading}
              maximized={artifactMaximized}
              overlay={artifactOverlay}
              restoreFocusRef={artifactButtonRef}
              onClose={() => {
                closeArtifact();
              }}
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
