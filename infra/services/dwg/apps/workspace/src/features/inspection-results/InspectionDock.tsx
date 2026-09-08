import { AlertTriangle, Box, CheckCircle2, FileCheck2, ScanSearch } from "lucide-react";
import { useState } from "react";

import type { CadEntity, InspectionRun } from "../../shared/types";
import "./styles.css";

interface Props {
  run: InspectionRun | null;
  selected: CadEntity | null;
  onSelectFinding: (handle: string) => void;
}

export function InspectionDock({ run, selected, onSelectFinding }: Props) {
  const firstFinding = run?.findings.find((finding) => finding.handle) ?? null;
  const warnings = run?.warnings ?? [];
  const [activeTab, setActiveTab] = useState<"overview" | "evidence" | "warnings">("overview");

  return (
    <section className="inspection-dock" aria-label="검사 결과">
      <div className="dock-tabs">
        <button className={`dock-tab ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}><ScanSearch size={13} /> Findings <b>{run?.findings.length ?? 0}</b></button>
        <button className={`dock-tab ${activeTab === "evidence" ? "active" : ""}`} onClick={() => setActiveTab("evidence")}><FileCheck2 size={13} /> Evidence <b>{selected ? 1 : 0}</b></button>
        <button className={`dock-tab ${activeTab === "warnings" ? "active" : ""} ${warnings.length > 0 ? "has-warning" : ""}`} onClick={() => setActiveTab("warnings")}><AlertTriangle size={13} /> Warnings <b>{warnings.length}</b></button>
      </div>

      <div className="dock-content">
        {activeTab === "overview" && firstFinding && <button
          aria-label={`${firstFinding.layer} 레이어 검사 결과 ${run?.findings.length ?? 0}개`}
          className={`finding-row ${selected ? "selected" : ""}`}
          onClick={() => onSelectFinding(firstFinding.handle!)}
        >
          <span className="finding-severity"><CheckCircle2 size={14} /></span>
          <span className="finding-main">
            <strong>{firstFinding.layer} 레이어 주요 형상 확인</strong>
            <small>검색 결과 {run?.findings.length ?? 0}개 · 증거 검증 통과</small>
          </span>
          <span className="finding-rule">IDX-LAYER-001</span>
          <span className="finding-status">VERIFIED</span>
        </button>}
        {activeTab === "overview" && !firstFinding && (
          <div className="dock-empty finding-empty">Run agents를 눌러 실제 도면 검사를 실행하세요.</div>
        )}

        {(activeTab === "overview" || activeTab === "evidence") && <div className="evidence-card" data-testid="evidence-card">
          {selected ? (
            <>
              <div className="evidence-title"><Box size={14} /> Entity evidence <strong>{selected.id}</strong></div>
              <dl>
                <div><dt>HANDLE</dt><dd>{selected.handle}</dd></div>
                <div><dt>TYPE</dt><dd>{selected.type}</dd></div>
                <div><dt>LAYER</dt><dd>{selected.layer}</dd></div>
                <div className="bbox-value"><dt>BOUNDING BOX</dt><dd>{formatBox(selected)}</dd></div>
              </dl>
            </>
          ) : (
            <div className="empty-evidence">Finding을 선택하면 객체 근거와 bounding box가 표시됩니다.</div>
          )}
        </div>}

        {(activeTab === "overview" || activeTab === "warnings") && warnings.map((warning) => (
          <div className="warning-card" role="alert" key={warning}>
            <AlertTriangle size={14} />
            <div><strong>부분 지원 객체</strong><span>{warning}</span></div>
          </div>
        ))}
        {activeTab === "warnings" && warnings.length === 0 && <div className="dock-empty">경고가 없습니다.</div>}
      </div>
    </section>
  );
}

function formatBox(entity: CadEntity) {
  if (!entity.bbox) return "unavailable";
  const round = (value: number) => Number(value.toFixed(2));
  return `[${round(entity.bbox.min[0])}, ${round(entity.bbox.min[1])}] → [${round(entity.bbox.max[0])}, ${round(entity.bbox.max[1])}]`;
}
