import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileCheck2,
  Maximize2,
  Minimize2,
  Play,
  RotateCcw,
  ScanSearch,
  Search,
  View,
  X
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { CadViewer } from "../features/cad-viewer/CadViewer";
import { ChangeReview } from "../features/change-review/ChangeReview";
import { useChangeReview } from "../features/change-review/useChangeReview";
import { ExportPanel } from "../features/export/ExportPanel";
import type { CadEntity, CadIndex, InspectionRun } from "../shared/types";
import { useModalOverlay } from "./useModalOverlay";

type ArtifactTab = "preview" | "findings" | "evidence" | "changes" | "export" | "warnings";

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
  overlay: boolean;
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
  overlay,
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
  const dialogRef = useRef<HTMLElement>(null);
  useModalOverlay({ active: overlay, dialogRef, restoreFocusRef, onClose });
  const revision = index.schemaVersion === "cad-index/v0.2" ? index.drawing?.revision ?? 0 : 0;
  const [tab, setTab] = useState<ArtifactTab>("preview");
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const findingGroups = useMemo(
    () => groupFindings(run?.findings ?? []),
    [run?.findings]
  );

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
      ref={dialogRef}
      role={overlay ? "dialog" : undefined}
    >
      <div className="artifact-header">
        <div className="artifact-title">
          <strong>{index.source.displayName}</strong>
          <span>Revision {revision}</span>
          <span><CheckCircle2 size={11} /> <b>Indexed</b> · {index.summary.modelSpaceCount} entities</span>
        </div>
        <label className="artifact-search">
          <Search size={13} />
          <input
            aria-label="전체 도면 검색"
            onChange={(event) => onSearchQueryChange(event.target.value)}
            placeholder="handle, layer, type"
            ref={searchInputRef}
            value={searchQuery}
          />
        </label>
        <button className="run-agents" disabled={inspectionLoading} onClick={onRunAgents}>
          <Play size={13} /> {inspectionLoading ? "Running" : "Run agents"}
        </button>
        {run && (
          <button aria-label="검사 초기화" className="icon-button" onClick={onResetInspection}>
            <RotateCcw size={14} />
          </button>
        )}
        <select
          aria-label="아티팩트 버전"
          className="artifact-version"
          onChange={() => undefined}
          value={index.schemaVersion}
        >
          <option value={index.schemaVersion}>{index.schemaVersion}</option>
        </select>
        <div className="artifact-actions">
          <button aria-label="아티팩트 복사" className="icon-button" onClick={() => void copyArtifact()}>
            <Copy size={14} />
          </button>
          <button aria-label="아티팩트 다운로드" className="icon-button" onClick={downloadArtifact}>
            <Download size={14} />
          </button>
          <button
            aria-label={maximized ? "아티팩트 복원" : "아티팩트 최대화"}
            className="icon-button"
            onClick={() => onMaximizedChange(!maximized)}
          >
            {maximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          <button aria-label="CAD 아티팩트 닫기" className="icon-button" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
      </div>
      <div className="artifact-tabs" role="tablist">
        <Tab active={tab === "preview"} icon={<View size={13} />} label="CAD Preview" onClick={() => setTab("preview")} />
        <Tab active={tab === "findings"} count={run?.findings.length ?? 0} icon={<ScanSearch size={13} />} label="Findings" onClick={() => setTab("findings")} />
        <Tab active={tab === "evidence"} count={selected ? 1 : 0} icon={<FileCheck2 size={13} />} label="Evidence" onClick={() => setTab("evidence")} />
        <Tab active={tab === "changes"} count={changeReview.preview?.changeCount} icon={<FileCheck2 size={13} />} label="Changes" onClick={() => setTab("changes")} />
        <Tab active={tab === "export"} icon={<Download size={13} />} label="Export" onClick={() => setTab("export")} />
        <Tab active={tab === "warnings"} count={run?.warnings.length ?? 0} icon={<AlertTriangle size={13} />} label="Warnings" onClick={() => setTab("warnings")} />
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
    <button aria-selected={active} className={active ? "active" : ""} onClick={onClick} role="tab">
      {icon}{label}{count !== undefined && <b>{count}</b>}
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
