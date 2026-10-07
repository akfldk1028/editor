import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileCheck2,
  FileDiff,
  Play,
  RotateCcw,
  ScanSearch,
  Search,
  View
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { CadViewer } from "../../features/cad-viewer/CadViewer";
import { ChangeReview } from "../../features/change-review/ChangeReview";
import { ExportPanel } from "../../features/export/ExportPanel";
import type { CadEntity, InspectionRun } from "../../shared/types";
import { closePopover } from "../../shared/usePopoverAnchor";
import { DwgLoadState } from "./DwgLoadState";
import { useDwgWorkspace } from "./DwgWorkspaceProvider";

export type DwgArtifactTab = "preview" | "findings" | "evidence" | "changes" | "export" | "warnings";

/**
 * The artifact's views. `overflow` views open from the ⋯ menu and join the
 * tab strip only while active; a host renders the strip from this list.
 */
export const dwgArtifactTabs: readonly { id: DwgArtifactTab; label: string; icon: typeof View; overflow?: true }[] = [
  { id: "preview", label: "CAD Preview", icon: View },
  { id: "findings", label: "Findings", icon: ScanSearch },
  { id: "changes", label: "Changes", icon: FileDiff },
  { id: "evidence", label: "Evidence", icon: FileCheck2, overflow: true },
  { id: "export", label: "Export", icon: Download, overflow: true },
  { id: "warnings", label: "Warnings", icon: AlertTriangle, overflow: true }
];

export interface DwgArtifactView {
  /** Title block: drawing name and index status line. */
  title: ReactNode;
  /** Primary header action (Run agents). */
  actions: ReactNode;
  /** Artifact-specific ⋯ menu rows (search, version, JSON actions). */
  menu: ReactNode;
  /** Badge counts per tab. */
  counts: Partial<Record<DwgArtifactTab, number>>;
  /** The active tab's content. */
  body: ReactNode;
}

/**
 * The CAD artifact as parts a host frame places in its own header, menu and
 * body. `onSelectTab` lets a finding jump to its evidence.
 */
export function useDwgArtifact({ tab, onSelectTab }: { tab: string; onSelectTab(tab: DwgArtifactTab): void }): DwgArtifactView {
  const workspace = useDwgWorkspace();
  const { index, inspection, changeReview, selected, searchQuery, searchRef } = workspace;
  const run = inspection.run;
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const findingGroups = useMemo(() => groupFindings(run?.findings ?? []), [run?.findings]);
  const revision = index?.schemaVersion === "cad-index/v0.2" ? index.drawing?.revision ?? 0 : 0;

  // Ctrl+K opens the ⋯ menu that holds the drawing search and focuses it.
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      const input = searchRef.current;
      const menu = input?.closest<HTMLElement>("[popover]");
      try {
        if (menu && !menu.matches(":popover-open")) menu.showPopover();
      } catch {
        // Unsupported popover: the input is still focusable when visible.
      }
      input?.focus();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [searchRef]);

  if (!index) {
    return { title: <strong>CAD 도면</strong>, actions: null, menu: null, counts: {}, body: <DwgLoadState /> };
  }
  const loadedIndex = index;

  function fromMenu(action: () => void) {
    return (event: React.MouseEvent<HTMLElement>) => {
      closePopover(event.currentTarget);
      action();
    };
  }

  async function copyArtifact() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(loadedIndex, null, 2));
    } catch {
      // Clipboard access can be denied by browser or host policy.
    }
  }

  function downloadArtifact() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(loadedIndex, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${loadedIndex.source.displayName.replace(/\.[^.]+$/, "")}.index.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const title = (
    <>
      <strong title={index.source.displayName}>{index.source.displayName}</strong>
      <span>
        <CheckCircle2 aria-hidden="true" size={12} /> <b>Indexed</b> · Revision {revision} · {index.summary.modelSpaceCount} entities
        {searchQuery && <> · <i>&ldquo;{searchQuery}&rdquo;</i></>}
      </span>
    </>
  );

  const actions = (
    <button className="run-agents artifact-primary" disabled={inspection.loading} onClick={() => void workspace.runAgents()}>
      <Play aria-hidden="true" size={14} /> <span>{inspection.loading ? "Running" : "Run agents"}</span>
    </button>
  );

  const menu = (
    <>
      <label className="menu-search">
        <Search aria-hidden="true" size={14} />
        <input
          aria-label="전체 도면 검색"
          onChange={(event) => workspace.setSearchQuery(event.target.value)}
          placeholder="handle, layer, type"
          ref={searchRef}
          type="search"
          value={searchQuery}
        />
        <kbd>Ctrl K</kbd>
      </label>
      <label className="menu-field">
        <span>버전</span>
        <select aria-label="아티팩트 버전" className="artifact-version" onChange={() => undefined} value={index.schemaVersion}>
          <option value={index.schemaVersion}>{index.schemaVersion}</option>
        </select>
      </label>
      <div aria-label="아티팩트 동작" className="menu-group" role="group">
        {run && (
          <button aria-label="검사 초기화" onClick={fromMenu(workspace.resetInspection)}>
            <RotateCcw aria-hidden="true" size={14} /><span>검사 초기화</span>
          </button>
        )}
        <button aria-label="아티팩트 복사" onClick={fromMenu(() => void copyArtifact())}>
          <Copy aria-hidden="true" size={14} /><span>JSON 복사</span>
        </button>
        <button aria-label="아티팩트 다운로드" onClick={fromMenu(downloadArtifact)}>
          <Download aria-hidden="true" size={14} /><span>JSON 다운로드</span>
        </button>
      </div>
    </>
  );

  const counts: DwgArtifactView["counts"] = {
    findings: run?.findings.length ?? 0,
    changes: changeReview.preview?.changeCount,
    evidence: selected ? 1 : 0,
    warnings: run?.warnings.length ?? 0
  };

  const body = (
    <div className="dwg-workspace dwg-artifact-body">
      {tab === "preview" && (
        <CadViewer
          gridVisible={workspace.gridVisible}
          highlightedHandles={workspace.highlightedHandles}
          hiddenLayers={workspace.layerVisibility.hiddenLayers}
          index={index}
          onGridVisibleChange={workspace.setGridVisible}
          searchQuery={searchQuery}
          selectedHandle={workspace.selectedHandle}
          showMaximize={false}
        />
      )}
      {tab === "findings" && (
        <div className="artifact-list">
          {findingGroups.map((group) => (
            <section className="finding-group" key={group.id}>
              <button
                aria-expanded={expandedGroup === group.id}
                aria-label={`${group.layer} ${group.type} ${group.findings.length}개`}
                className="finding-group-heading"
                onClick={() => setExpandedGroup((current) => current === group.id ? null : group.id)}
              >
                {expandedGroup === group.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <span><strong>{group.layer} · {group.type}</strong><small>{group.findings.length} entities</small></span>
                <b>{group.findings.length}</b>
              </button>
              {expandedGroup === group.id && (
                <div className="finding-group-entities">
                  {group.findings.map((finding, indexValue) => (
                    <button
                      aria-label={`${finding.layer} 레이어 검사 결과 ${group.findings.length}개`}
                      className="artifact-card finding-card finding-row"
                      key={`${finding.handle}:${indexValue}`}
                      onClick={() => {
                        if (!finding.handle) return;
                        workspace.setSelectedHandle(finding.handle);
                        onSelectTab("evidence");
                      }}
                    >
                      <ScanSearch size={15} />
                      <span><strong>{finding.type}</strong><small>handle {finding.handle ?? "none"}</small></span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          ))}
          {!run?.findings.length && <Empty>검사를 실행하면 근거가 표시됩니다.</Empty>}
        </div>
      )}
      {tab === "evidence" && (
        selected
          ? <Evidence entity={selected} revision={revision} />
          : <Empty>Finding을 선택하면 handle, layer, type, bbox를 표시합니다.</Empty>
      )}
      {tab === "changes" && (
        <ChangeReview
          busy={changeReview.busy}
          documentId={index.drawingId}
          error={changeReview.error}
          expectedRevision={changeReview.revision ?? 0}
          mutationBusy={changeReview.mutationBusy}
          onApprove={changeReview.approve}
          onRePreview={changeReview.rePreview}
          onRedo={changeReview.redo}
          onReject={changeReview.reject}
          onRetry={changeReview.retry}
          onUndo={changeReview.undo}
          phase={changeReview.phase}
          preview={changeReview.preview}
          proposalError={workspace.proposalError}
          revision={changeReview.revision}
          retryAction={changeReview.retryAction}
          selectedEntity={selected}
        />
      )}
      {tab === "export" && <ExportPanel />}
      {tab === "warnings" && (
        <div className="artifact-list">
          {run?.warnings.map((warning) => (
            <div className="artifact-card warning-card" key={warning}>
              <AlertTriangle size={15} /><span>{warning}</span>
            </div>
          ))}
          {!run?.warnings.length && <Empty>경고가 없습니다.</Empty>}
        </div>
      )}
    </div>
  );

  return { title, actions, menu, counts, body };
}

function groupFindings(findings: InspectionRun["findings"]) {
  const groups = new Map<string, { id: string; layer: string; type: string; findings: InspectionRun["findings"] }>();
  findings.forEach((finding) => {
    const id = `${finding.layer}\u0000${finding.type}`;
    const group = groups.get(id);
    if (group) {
      group.findings.push(finding);
      return;
    }
    groups.set(id, { id, layer: finding.layer, type: finding.type, findings: [finding] });
  });
  return [...groups.values()].sort(
    (left, right) =>
      right.findings.length - left.findings.length ||
      left.layer.localeCompare(right.layer) ||
      left.type.localeCompare(right.type)
  );
}

function Evidence({ entity, revision }: { entity: CadEntity; revision: number }) {
  return (
    <dl className="evidence-grid" data-testid="evidence-card">
      <div><dt>HANDLE</dt><dd>{entity.handle}</dd></div>
      <div><dt>TYPE</dt><dd>{entity.type}</dd></div>
      <div><dt>LAYER</dt><dd>{entity.layer}</dd></div>
      <div><dt>BOUNDING BOX</dt><dd>{entity.bbox ? JSON.stringify(entity.bbox) : "unavailable"}</dd></div>
      <div><dt>REVISION</dt><dd>{revision}</dd></div>
    </dl>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="artifact-empty">{children}</div>;
}
