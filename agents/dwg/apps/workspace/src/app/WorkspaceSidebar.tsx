import { PanelLeftClose, Search } from "lucide-react";
import { useEffect, useRef } from "react";

import { ProjectNavigator } from "../features/project-navigation/ProjectNavigator";
import { SessionNavigator, type SessionNavigationItem } from "../features/session-navigation/SessionNavigator";
import { SkillNavigator } from "../features/skill-navigation/SkillNavigator";
import type { CadIndex } from "../shared/types";
import type { SidebarTab } from "./workspacePreferences";
import { useModalOverlay } from "./useModalOverlay";

interface Props {
  activeSessionId: string | null;
  /** Composed by App: features never import one another. */
  drawingSessions?: React.ReactNode;
  hiddenLayers: ReadonlySet<string>;
  index: CadIndex;
  overlay: boolean;
  query: string;
  sessions: readonly SessionNavigationItem[];
  tab: SidebarTab;
  restoreFocusRef?: React.RefObject<HTMLElement | null>;
  onClose(): void;
  onNewSession(): void;
  onQueryChange(query: string): void;
  onSelectSession(id: string): void;
  onSelectTab(tab: SidebarTab): void;
  onToggleLayer(layerName: string): void;
}

const tabs: readonly SidebarTab[] = ["project", "sessions", "skills"];

export function WorkspaceSidebar({
  activeSessionId,
  drawingSessions,
  hiddenLayers,
  index,
  overlay,
  query,
  sessions,
  tab,
  restoreFocusRef,
  onClose,
  onNewSession,
  onQueryChange,
  onSelectSession,
  onSelectTab,
  onToggleLayer
}: Props) {
  const dialogRef = useRef<HTMLElement>(null);
  useModalOverlay({ active: overlay, dialogRef, restoreFocusRef, onClose });

  function moveTab(current: SidebarTab, direction: 1 | -1) {
    const currentIndex = tabs.indexOf(current);
    const next = tabs[(currentIndex + direction + tabs.length) % tabs.length]!;
    onSelectTab(next);
    window.requestAnimationFrame(() => document.getElementById(`workspace-tab-${next}`)?.focus());
  }

  function onTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, current: SidebarTab) {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      moveTab(current, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      moveTab(current, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      onSelectTab("project");
      window.requestAnimationFrame(() => document.getElementById("workspace-tab-project")?.focus());
    } else if (event.key === "End") {
      event.preventDefault();
      onSelectTab("skills");
      window.requestAnimationFrame(() => document.getElementById("workspace-tab-skills")?.focus());
    }
  }

  return (
    <aside
      aria-label="Workspace navigation"
      aria-modal={overlay ? true : undefined}
      className={`workspace-sidebar ${overlay ? "overlay modal-overlay" : ""}`}
      data-modal-background
      ref={dialogRef}
      role={overlay ? "dialog" : undefined}
    >
      <div className="sidebar-heading">
        <div className="brand-mark">DI</div><strong>DWG Intelligence</strong>
        {overlay && <button aria-label="Close navigation" className="icon-button" onClick={onClose}><PanelLeftClose size={16} /></button>}
      </div>

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
        >{candidate === "project" ? "Project" : candidate === "sessions" ? "Sessions" : "Skills"}</button>)}
      </div>

      {drawingSessions}

      <label className="sidebar-search">
        <Search aria-hidden="true" size={13} />
        <input aria-label="Search workspace" onChange={(event) => onQueryChange(event.target.value)} placeholder="Search workspace" value={query} />
      </label>

      <div className="sidebar-panel" id={`workspace-panel-${tab}`} role="tabpanel" aria-labelledby={`workspace-tab-${tab}`}>
        {tab === "project" && <ProjectNavigator hiddenLayers={hiddenLayers} index={index} onToggleLayer={onToggleLayer} query={query} />}
        {tab === "sessions" && <SessionNavigator activeSessionId={activeSessionId} onNewSession={onNewSession} onSelectSession={onSelectSession} query={query} sessions={sessions} />}
        {tab === "skills" && <SkillNavigator query={query} />}
      </div>
    </aside>
  );
}
