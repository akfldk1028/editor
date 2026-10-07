import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileCheck2,
  FileDiff,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  Play,
  RotateCcw,
  ScanSearch,
  Search,
  View,
  X
} from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";

import { CadViewer } from "../features/cad-viewer/CadViewer";
import { ChangeReview } from "../features/change-review/ChangeReview";
import { useChangeReview } from "../features/change-review/useChangeReview";
import { ExportPanel } from "../features/export/ExportPanel";
import type { CadEntity, CadIndex, InspectionRun } from "../shared/types";
import type { ArtifactPresentation } from "./layoutModes";
import { useModalOverlay } from "./useModalOverlay";
import { closePopover, usePopoverAnchor } from "../shared/usePopoverAnchor";

type ArtifactTab = "preview" | "findings" | "evidence" | "changes" | "export" | "warnings";

/** Always in the tab strip; the others open from the overflow menu and join the strip while active. */
const coreTabs: readonly ArtifactTab[] = ["preview", "findings", "changes"];

interface Props {
  index: CadIndex;
  run: InspectionRun | null;
  selected: CadEntity | null;
  highlightedHandles: ReadonlySet<string>;
  selectedHandle: string | null;
  changeReview: ReturnType<typeof useChangeReview>;
  proposalError: string | null;
  searchQuery: string;
  gridVisible: boolean;
  hiddenLayers: ReadonlySet<string>;
  maximized: boolean;
  presentation: ArtifactPresentation;
  restoreFocusRef?: React.RefObject<HTMLElement | null>;
  inspectionLoading: boolean;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
  onClose(): void;
  onGridVisibleChange(visible: boolean): void;
  onMaximizedChange(maximized: boolean): void;
  onResetInspection(): void;
  onRunAgents(): void;
  onSearchQueryChange(query: string): void;
  onSelectFinding(handle: string): void;
}

export function CadArtifactPanel({
  index,
  run,
  selected,
  highlightedHandles,
  selectedHandle,
  changeReview,
  proposalError,
  searchQuery,
  gridVisible,
  hiddenLayers,
  maximized,
  presentation,
  restoreFocusRef,
  inspectionLoading,
  searchInputRef,
  onClose,
  onGridVisibleChange,
  onMaximizedChange,
  onResetInspection,
  onRunAgents,
  onSearchQueryChange,
  onSelectFinding
}: Props) {
  const overlay = presentation === "sheet";
  const dialogRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  useModalOverlay({ active: overlay, dialogRef, restoreFocusRef, onClose });
  usePopoverAnchor(menuRef, menuButtonRef);
  const revision = index.schemaVersion === "cad-index/v0.2" ? index.drawing?.revision ?? 0 : 0;
  const [tab, setTab] = useState<ArtifactTab>("preview");
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const findingGroups = useMemo(
    () => groupFindings(run?.findings ?? []),
    [run?.findings]
  );
  const tabMeta: Record<ArtifactTab, { label: string; icon: React.ReactNode; count?: number }> = {
    preview: { label: "CAD Preview", icon: <View aria-hidden="true" size={14} /> },
    findings: { label: "Findings", icon: <ScanSearch aria-hidden="true" size={14} />, count: run?.findings.length ?? 0 },
    changes: { label: "Changes", icon: <FileDiff aria-hidden="true" size={14} />, count: changeReview.preview?.changeCount },
    evidence: { label: "Evidence", icon: <FileCheck2 aria-hidden="true" size={14} />, count: selected ? 1 : 0 },
    export: { label: "Export", icon: <Download aria-hidden="true" size={14} /> },
    warnings: { label: "Warnings", icon: <AlertTriangle aria-hidden="true" size={14} />, count: run?.warnings.length ?? 0 }
  };
  const stripTabs = coreTabs.includes(tab) ? coreTabs : [...coreTabs, tab];

  function fromMenu(action: () => void) {
    return () => {
      closePopover(menuRef.current);
      action();
    };
  }

  async function copyArtifact() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(index, null, 2));
    } catch {
      // Clipboard access can be denied by browser or host policy.
    }
  }

  function downloadArtifact() {
    const url = URL.createObjectURL(new Blob(
      [JSON.stringify(index, null, 2)],
      { type: "application/json" }
    ));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${index.source.displayName.replace(/\.[^.]+$/, "")}.index.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section
      aria-label="CAD 아티팩트"
      aria-modal={overlay ? true : undefined}
      className={`cad-artifact ${maximized ? "maximized" : ""} ${overlay ? "modal-overlay" : ""}`}
      data-modal-background
      data-maximized={maximized}
      data-presentation={presentation}
      ref={dialogRef}
      role={overlay ? "dialog" : undefined}
    >
      <div className="artifact-header">
        <div className="artifact-title">
          <strong title={index.source.displayName}>{index.source.displayName}</strong>
          <span>
            <CheckCircle2 aria-hidden="true" size={12} /> <b>Indexed</b> · Revision {revision} · {index.summary.modelSpaceCount} entities
            {searchQuery && <> · <i>&ldquo;{searchQuery}&rdquo;</i></>}
          </span>
        </div>
        <button className="run-agents" disabled={inspectionLoading} onClick={onRunAgents}>
          <Play aria-hidden="true" size={14} /> <span>{inspectionLoading ? "Running" : "Run agents"}</span>
        </button>
        <button
          aria-haspopup="menu"
          aria-label="아티팩트 메뉴"
          className="icon-button"
          popoverTarget={menuId}
          ref={menuButtonRef}
          title="아티팩트 메뉴"
        >
          <MoreHorizontal size={16} />
        </button>
        <button aria-label="CAD 아티팩트 닫기" className="icon-button artifact-close" onClick={onClose} title="닫기">
          <X size={16} />
        </button>
        <div className="workspace-menu artifact-menu" id={menuId} popover="auto" ref={menuRef}>
          <label className="menu-search">
            <Search aria-hidden="true" size={14} />
            <input
              aria-label="전체 도면 검색"
              onChange={(event) => onSearchQueryChange(event.target.value)}
              placeholder="handle, layer, type"
              ref={searchInputRef}
              type="search"
              value={searchQuery}
            />
            <kbd>Ctrl K</kbd>
          </label>
          <label className="menu-field">
            <span>버전</span>
            <select
              aria-label="아티팩트 버전"
              className="artifact-version"
              onChange={() => undefined}
              value={index.schemaVersion}
            >
              <option value={index.schemaVersion}>{index.schemaVersion}</option>
            </select>
          </label>
          <div aria-label="보기" className="menu-group" role="group">
            {(["evidence", "export", "warnings"] as const).map((candidate) => (
              <button aria-current={tab === candidate ? "true" : undefined} key={candidate} onClick={fromMenu(() => setTab(candidate))}>
                {tabMeta[candidate].icon}<span>{tabMeta[candidate].label}</span>
                {tabMeta[candidate].count !== undefined && <b>{tabMeta[candidate].count}</b>}
              </button>
            ))}
          </div>
          <div aria-label="아티팩트 동작" className="menu-group" role="group">
            {run && (
              <button aria-label="검사 초기화" onClick={fromMenu(onResetInspection)}>
                <RotateCcw aria-hidden="true" size={14} /><span>검사 초기화</span>
              </button>
            )}
            <button aria-label="아티팩트 복사" onClick={fromMenu(() => void copyArtifact())}>
              <Copy aria-hidden="true" size={14} /><span>JSON 복사</span>
            </button>
            <button aria-label="아티팩트 다운로드" onClick={fromMenu(downloadArtifact)}>
              <Download aria-hidden="true" size={14} /><span>JSON 다운로드</span>
            </button>
            {presentation !== "panel" && (
              <button
                aria-label={maximized ? "아티팩트 복원" : "아티팩트 최대화"}
                onClick={fromMenu(() => onMaximizedChange(!maximized))}
              >
                {maximized ? <Minimize2 aria-hidden="true" size={14} /> : <Maximize2 aria-hidden="true" size={14} />}
                <span>{maximized ? "원래 크기" : "최대화"}</span>
              </button>
            )}
          </div>
        </div>
      </div>
      <div aria-label="아티팩트 보기" className="artifact-tabs" role="tablist">
        {stripTabs.map((candidate) => (
          <Tab
            active={tab === candidate}
            count={tabMeta[candidate].count}
            icon={tabMeta[candidate].icon}
            key={candidate}
            label={tabMeta[candidate].label}
            onClick={() => setTab(candidate)}
          />
        ))}
      </div>
      <div className="artifact-content">
        {tab === "preview" && (
          <CadViewer
            gridVisible={gridVisible}
            highlightedHandles={highlightedHandles}
            hiddenLayers={hiddenLayers}
            index={index}
            onGridVisibleChange={onGridVisibleChange}
            searchQuery={searchQuery}
            selectedHandle={selectedHandle}
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
                          onSelectFinding(finding.handle);
                          setTab("evidence");
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
            proposalError={proposalError}
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
    </section>
  );
}

function groupFindings(findings: InspectionRun["findings"]) {
  const groups = new Map<string, {
    id: string;
    layer: string;
    type: string;
    findings: InspectionRun["findings"];
  }>();
  findings.forEach((finding) => {
    const id = `${finding.layer}\u0000${finding.type}`;
    const group = groups.get(id);
    if (group) {
      group.findings.push(finding);
      return;
    }
    groups.set(id, {
      id,
      layer: finding.layer,
      type: finding.type,
      findings: [finding]
    });
  });
  return [...groups.values()].sort(
    (left, right) =>
      right.findings.length - left.findings.length ||
      left.layer.localeCompare(right.layer) ||
      left.type.localeCompare(right.type)
  );
}

function Tab({ active, icon, label, count, onClick }: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  count?: number;
  onClick(): void;
}) {
  return (
    <button aria-selected={active} className={active ? "active" : ""} onClick={onClick} role="tab" title={label}>
      {icon}<span className="tab-label">{label}</span>{count !== undefined && <b>{count}</b>}
    </button>
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

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="artifact-empty">{children}</div>;
}
