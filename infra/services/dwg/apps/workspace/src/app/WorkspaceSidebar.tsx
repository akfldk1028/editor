import { FolderTree, History, PanelLeftClose, PanelLeftOpen, Search, Sparkles } from "lucide-react";
import { useRef } from "react";

import { ProjectNavigator } from "../features/project-navigation/ProjectNavigator";
import { SessionNavigator, type SessionNavigationItem } from "../features/session-navigation/SessionNavigator";
import { SkillNavigator } from "../features/skill-navigation/SkillNavigator";
import type { CadIndex } from "../shared/types";
import type { SidebarPresentation } from "./useWorkspaceControls";
import type { SidebarTab } from "./workspacePreferences";
import { useModalOverlay } from "./useModalOverlay";

interface Props {
  activeSessionId: string | null;
  /** Composed by App: features never import one another. */
  drawingSessions?: React.ReactNode;
  /** Extra controls for the heading row (e.g. open drawing). */
  headingActions?: React.ReactNode;
  hiddenLayers: ReadonlySet<string>;
  index: CadIndex;
  presentation: Exclude<SidebarPresentation, "hidden">;
  query: string;
  sessions: readonly SessionNavigationItem[];
  tab: SidebarTab;
  restoreFocusRef?: React.RefObject<HTMLElement | null>;
  onClose(): void;
  onExpandedChange(expanded: boolean): void;
  onNewSession(): void;
  onQueryChange(query: string): void;
  onSelectSession(id: string): void;
  onSelectTab(tab: SidebarTab): void;
  onToggleLayer(layerName: string): void;
}

const tabs: readonly SidebarTab[] = ["project", "sessions", "skills"];
const tabLabels: Record<SidebarTab, string> = { project: "Project", sessions: "Sessions", skills: "Skills" };
const tabIcons: Record<SidebarTab, React.ReactNode> = {
  project: <FolderTree aria-hidden="true" size={16} />,
  sessions: <History aria-hidden="true" size={16} />,
  skills: <Sparkles aria-hidden="true" size={16} />
};

export function WorkspaceSidebar({
  activeSessionId,
  drawingSessions,
  headingActions,
  hiddenLayers,
  index,
  presentation,
  query,
  sessions,
  tab,
  restoreFocusRef,
  onClose,
  onExpandedChange,
  onNewSession,
  onQueryChange,
  onSelectSession,
  onSelectTab,
  onToggleLayer
}: Props) {
  const overlay = presentation === "drawer";
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

  if (presentation === "rail") {
    return (
      <aside aria-label="Workspace navigation" className="workspace-sidebar rail" data-modal-background>
        <button aria-label="Expand navigation" className="icon-button" onClick={() => onExpandedChange(true)} title="탐색 펼치기">
          <PanelLeftOpen size={16} />
        </button>
        {tabs.map((candidate) => (
          <button
            aria-label={tabLabels[candidate]}
            aria-pressed={candidate === tab}
            className="icon-button"
            key={candidate}
            onClick={() => {
              onSelectTab(candidate);
              onExpandedChange(true);
            }}
            title={tabLabels[candidate]}
          >
            {tabIcons[candidate]}
          </button>
        ))}
      </aside>
    );
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
        <div aria-hidden="true" className="brand-mark">DI</div><strong>DWG Intelligence</strong>
        <span className="sidebar-heading-actions">
          {/* In the drawer, close comes first so the dialog's initial focus lands on it. */}
          {overlay && <button aria-label="Close navigation" className="icon-button" onClick={onClose} title="닫기"><PanelLeftClose size={16} /></button>}
          {headingActions}
          {!overlay && <button aria-label="Collapse navigation" className="icon-button" onClick={() => onExpandedChange(false)} title="탐색 접기"><PanelLeftClose size={16} /></button>}
        </span>
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
        >{tabLabels[candidate]}</button>)}
      </div>

      <label className="sidebar-search">
        <Search aria-hidden="true" size={14} />
        <input aria-label="Search workspace" onChange={(event) => onQueryChange(event.target.value)} placeholder="Search workspace" type="search" value={query} />
      </label>

      {drawingSessions}

      <div className="sidebar-panel" id={`workspace-panel-${tab}`} role="tabpanel" aria-labelledby={`workspace-tab-${tab}`}>
        {tab === "project" && <ProjectNavigator hiddenLayers={hiddenLayers} index={index} onToggleLayer={onToggleLayer} query={query} />}
        {tab === "sessions" && <SessionNavigator activeSessionId={activeSessionId} onNewSession={onNewSession} onSelectSession={onSelectSession} query={query} sessions={sessions} />}
        {tab === "skills" && <SkillNavigator query={query} />}
      </div>
    </aside>
  );
}
