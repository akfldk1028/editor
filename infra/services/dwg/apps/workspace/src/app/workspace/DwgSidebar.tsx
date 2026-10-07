import { Search } from "lucide-react";

import { DrawingSessionBar, OpenDrawingButton } from "../../features/drawing-sessions/DrawingSessionBar";
import { ProjectNavigator } from "../../features/project-navigation/ProjectNavigator";
import { SessionNavigator } from "../../features/session-navigation/SessionNavigator";
import { SkillNavigator } from "../../features/skill-navigation/SkillNavigator";
import { useDwgWorkspace, type DwgSidebarTab } from "./DwgWorkspaceProvider";
import { DwgLoadState } from "./DwgLoadState";

const tabs: readonly DwgSidebarTab[] = ["project", "sessions", "skills"];
const tabLabels: Record<DwgSidebarTab, string> = { project: "Project", sessions: "Sessions", skills: "Skills" };

/** Controls for the sidebar heading row (open another drawing). */
export function DwgSidebarActions() {
  return <OpenDrawingButton {...useDwgWorkspace().drawingSessionProps} />;
}

/**
 * The DWG navigation: section tabs, search, open drawings and the active
 * section. The frame around it (heading, collapse, drawer) belongs to the host.
 */
export function DwgSidebar() {
  const workspace = useDwgWorkspace();
  const { index, sidebarTab: tab, setSidebarTab: onSelectTab, sidebarQuery: query, chat, layerVisibility } = workspace;

  function focusTab(next: DwgSidebarTab) {
    onSelectTab(next);
    window.requestAnimationFrame(() => document.getElementById(`workspace-tab-${next}`)?.focus());
  }

  function onTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, current: DwgSidebarTab) {
    const position = tabs.indexOf(current);
    const next = {
      ArrowRight: tabs[(position + 1) % tabs.length],
      ArrowDown: tabs[(position + 1) % tabs.length],
      ArrowLeft: tabs[(position - 1 + tabs.length) % tabs.length],
      ArrowUp: tabs[(position - 1 + tabs.length) % tabs.length],
      Home: tabs[0],
      End: tabs[tabs.length - 1]
    }[event.key];
    if (!next) return;
    event.preventDefault();
    focusTab(next);
  }

  return (
    <div className="dwg-workspace dwg-sidebar-content">
      <div aria-label="Workspace navigation sections" className="sidebar-tabs" role="tablist">
        {tabs.map((candidate) => <button
          aria-controls={`workspace-panel-${candidate}`}
          aria-selected={candidate === tab}
          id={`workspace-tab-${candidate}`}
          key={candidate}
          onClick={() => onSelectTab(candidate)}
          onKeyDown={(event) => onTabKeyDown(event, candidate)}
          role="tab"
          tabIndex={candidate === tab ? 0 : -1}
          type="button"
        >{tabLabels[candidate]}</button>)}
      </div>

      <label className="sidebar-search">
        <Search aria-hidden="true" size={14} />
        <input aria-label="Search workspace" onChange={(event) => workspace.setSidebarQuery(event.target.value)} placeholder="Search workspace" type="search" value={query} />
      </label>

      <DrawingSessionBar {...workspace.drawingSessionProps} />

      <div className="sidebar-panel" id={`workspace-panel-${tab}`} role="tabpanel" aria-labelledby={`workspace-tab-${tab}`}>
        {tab === "project" && (index
          ? <ProjectNavigator hiddenLayers={layerVisibility.hiddenLayers} index={index} onToggleLayer={layerVisibility.toggleLayer} query={query} />
          : <DwgLoadState />)}
        {tab === "sessions" && <SessionNavigator activeSessionId={chat.activeSessionId} onNewSession={chat.reset} onSelectSession={chat.selectSession} query={query} sessions={chat.sessions} />}
        {tab === "skills" && <SkillNavigator query={query} />}
      </div>
    </div>
  );
}
