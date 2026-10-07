import { MoreHorizontal } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { usePopoverAnchor } from "../shared/usePopoverAnchor";
import { dwgArtifactTabs, useDwgArtifact, type DwgArtifactTab } from "./workspace/DwgArtifact";
import { DwgConversation, DwgConversationActions, DwgConversationHeading } from "./workspace/DwgConversation";
import { DwgSidebar, DwgSidebarActions } from "./workspace/DwgSidebar";
import { DwgWorkspaceProvider } from "./workspace/DwgWorkspaceProvider";
import "./styles.css";

/**
 * Standalone CAD workspace (the Vite dev app). A fixed three-column frame
 * around the public pieces; the responsive shell (layout modes, resizing,
 * drawers) is the host editor's.
 */
export function App() {
  return (
    <div className="dwg-workspace">
      <DwgWorkspaceProvider>
        <StandaloneFrame />
      </DwgWorkspaceProvider>
    </div>
  );
}

function useSystemTheme() {
  const [dark, setDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return dark ? "dark" : "light";
}

function StandaloneFrame() {
  const theme = useSystemTheme();
  const [tab, setTab] = useState<DwgArtifactTab>("preview");
  const artifact = useDwgArtifact({ tab, onSelectTab: setTab });
  const menuRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  usePopoverAnchor(menuRef, menuButtonRef);
  const strip = dwgArtifactTabs.filter((candidate) => !candidate.overflow || candidate.id === tab);

  return (
    <div className="app-shell standalone-frame" data-theme={theme}>
      <aside aria-label="Workspace navigation" className="workspace-sidebar">
        <div className="sidebar-heading">
          <div aria-hidden="true" className="brand-mark">DI</div><strong>DWG Intelligence</strong>
          <span className="sidebar-heading-actions"><DwgSidebarActions /></span>
        </div>
        <DwgSidebar />
      </aside>
      <header className="topbar">
        <DwgConversationHeading />
        <div className="topbar-actions"><DwgConversationActions /></div>
      </header>
      <DwgConversation />
      <section aria-label="CAD 아티팩트" className="cad-artifact">
        <div className="artifact-header">
          <div className="artifact-title">{artifact.title}</div>
          {artifact.actions}
          <button aria-haspopup="menu" aria-label="아티팩트 메뉴" className="icon-button" popoverTarget={menuId} ref={menuButtonRef} title="아티팩트 메뉴">
            <MoreHorizontal size={16} />
          </button>
          <div className="workspace-menu artifact-menu" id={menuId} popover="auto" ref={menuRef}>
            {artifact.menu}
            <div aria-label="보기" className="menu-group" role="group">
              {dwgArtifactTabs.filter((candidate) => candidate.overflow).map(({ id, label, icon: Icon }) => (
                <button aria-current={tab === id ? "true" : undefined} key={id} onClick={() => { menuRef.current?.hidePopover(); setTab(id); }}>
                  <Icon aria-hidden="true" size={14} /><span>{label}</span>
                  {artifact.counts[id] !== undefined && <b>{artifact.counts[id]}</b>}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div aria-label="아티팩트 보기" className="artifact-tabs" role="tablist">
          {strip.map(({ id, label, icon: Icon }) => (
            <button aria-selected={tab === id} className={tab === id ? "active" : ""} key={id} onClick={() => setTab(id)} role="tab" title={label}>
              <Icon aria-hidden="true" size={14} /><span className="tab-label">{label}</span>
              {artifact.counts[id] !== undefined && <b>{artifact.counts[id]}</b>}
            </button>
          ))}
        </div>
        <div className="artifact-content">{artifact.body}</div>
      </section>
    </div>
  );
}
