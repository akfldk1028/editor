import { AlertTriangle, CheckCircle2, History, RotateCcw, RotateCw, XCircle } from "lucide-react";

import type { CadChange, CadEntityChangeState, CadEntityIndexItem, CadLayerChangeState } from "@dwg/contracts";

import { ChangeProposalComposer } from "./ChangeProposalComposer";
import type { ChangeReviewPhase, ChangeReviewRetry } from "./useChangeReview";
import "./styles.css";

interface Props {
  phase: ChangeReviewPhase;
  preview: { baseRevision: number; nextRevision: number; changeCount: number; changesTruncated: boolean; changes: CadChange[]; warningCount: number; warningsTruncated: boolean; warnings: string[] } | null;
  revision: number | null;
  error: string | null;
  proposalError: string | null;
  documentId: string;
  expectedRevision: number;
  selectedEntity: CadEntityIndexItem | null;
  mutationBusy: boolean;
  retryAction: ChangeReviewRetry;
  busy: boolean;
  onApprove(): void;
  onReject(): void;
  onRetry(): void;
  onRePreview(): void;
  onUndo(): void;
  onRedo(): void;
}

export function ChangeReview({
  phase,
  preview,
  revision,
  error,
  proposalError,
  documentId,
  expectedRevision,
  selectedEntity,
  mutationBusy,
  retryAction,
  busy,
  onApprove,
  onReject,
  onRetry,
  onRePreview,
  onUndo,
  onRedo
}: Props) {
  const groups = preview ? groupChanges(preview.changes) : [];
  const canApprove = phase === "ready";
  const canUndo = phase === "applied" || phase === "redone";
  const canRedo = phase === "undone";
  const canRePreview = phase === "rejected" || phase === "stale";

  return (
    <section aria-label="Change review" className="change-review" role="region">
      <ChangeProposalComposer
        documentId={documentId}
        disabled={mutationBusy}
        expectedRevision={expectedRevision}
        selectedEntity={selectedEntity}
      />
      <header className="change-review-header">
        <div>
          <strong>Change review</strong>
          {preview && <span>Revision {preview.baseRevision} → {preview.nextRevision}</span>}
        </div>
        <Status phase={phase} revision={revision} />
      </header>
      {(proposalError || error) && <div className="change-review-error" role="alert">{proposalError ?? error}</div>}
      {!preview && <div className="change-review-empty">No proposed changes to review.</div>}
      {!preview && retryAction === "preview" && (
        <button className="change-review-retry" disabled={busy} onClick={onRetry}>Retry preview</button>
      )}
      {preview && (
        <>
          <div className="change-review-summary">
            <span>{preview.changeCount} change{preview.changeCount === 1 ? "" : "s"}</span>
            {preview.changesTruncated && <span>{preview.changeCount - preview.changes.length} additional change{preview.changeCount - preview.changes.length === 1 ? "" : "s"} not shown</span>}
          </div>
          {groups.map((group) => (
            <section className="change-group" key={group.kind}>
              <h3>{group.label}<small>{group.changes.length} change{group.changes.length === 1 ? "" : "s"}</small></h3>
              {group.changes.map((change) => <ChangeCard change={change} key={`${change.commandId}:${change.targetId}`} />)}
            </section>
          ))}
          <Warnings count={preview.warningCount} truncated={preview.warningsTruncated} warnings={preview.warnings} />
          <div className="change-review-actions">
            <button disabled={busy || !canApprove} onClick={onApprove}>Approve changes</button>
            <button disabled={busy || !canApprove} onClick={onReject}>Reject changes</button>
            <button disabled={busy || !canRePreview} onClick={onRePreview}>Re-preview changes</button>
            {phase === "error" && retryAction && retryAction !== "preview" && (
              <button disabled={busy} onClick={onRetry}>Retry {retryAction}</button>
            )}
            <button disabled={busy || !canUndo} onClick={onUndo}><RotateCcw size={13} />Undo changes</button>
            <button disabled={busy || !canRedo} onClick={onRedo}><RotateCw size={13} />Redo changes</button>
          </div>
        </>
      )}
    </section>
  );
}

function Status({ phase, revision }: { phase: ChangeReviewPhase; revision: number | null }) {
  if (phase === "ready") return <span className="change-review-status" role="status">Ready for approval</span>;
  if (phase === "previewing") return <span className="change-review-status" role="status">Previewing changes</span>;
  if (phase === "applying") return <span className="change-review-status" role="status">Applying changes</span>;
  if (phase === "rejected") return <span className="change-review-status" role="status"><XCircle size={13} />Changes rejected</span>;
  if (phase === "applied") return <span className="change-review-status" role="status"><CheckCircle2 size={13} />Applied at revision {revision}</span>;
  if (phase === "undoing") return <span className="change-review-status" role="status">Undoing changes</span>;
  if (phase === "undone") return <span className="change-review-status" role="status"><History size={13} />Undone at revision {revision}</span>;
  if (phase === "redoing") return <span className="change-review-status" role="status">Redoing changes</span>;
  if (phase === "redone") return <span className="change-review-status" role="status"><History size={13} />Redone at revision {revision}</span>;
  if (phase === "stale") return <span className="change-review-status" role="status"><AlertTriangle size={13} />Preview is stale</span>;
  return null;
}

function Warnings({ count, truncated, warnings }: { count: number; truncated: boolean; warnings: string[] }) {
  if (count === 0) return null;
  return <section className="change-warnings" aria-label="Change warnings">
    <h3><AlertTriangle size={14} />Warnings <small>{count}</small></h3>
    {warnings.map((warning, index) => <div key={`${warning}:${index}`}>{bounded(warning)}</div>)}
    {truncated && <small>{count - warnings.length} additional warning{count - warnings.length === 1 ? "" : "s"} not shown</small>}
  </section>;
}

function ChangeCard({ change }: { change: CadChange }) {
  const isLayer = change.kind === "layer.create" || change.kind === "layer.update";
  return <article className="change-card">
    <header><strong>{change.kind}</strong><small>{bounded(change.targetId)}</small></header>
    <div className="change-card-states">
      <Evidence title="Before" state={change.before} layer={isLayer} />
      <Evidence title="After" state={change.after} layer={isLayer} />
    </div>
  </article>;
}

function Evidence({ title, state, layer }: { title: string; state: CadEntityChangeState | CadLayerChangeState | null; layer: boolean }) {
  if (!state) return <section className="change-evidence"><h4>{title}</h4><span>Not present</span></section>;
  if (layer) {
    const value = state as CadLayerChangeState;
    return <section className="change-evidence"><h4>{title}</h4><dl>
      <div><dt>NAME</dt><dd>{bounded(value.name)}</dd></div>
      <div><dt>COLOR</dt><dd>{value.color ?? "unknown"}</dd></div>
      <div><dt>VISIBLE</dt><dd>{String(value.visible)}</dd></div>
      <div><dt>LOCKED</dt><dd>{value.locked === null ? "unknown" : String(value.locked)}</dd></div>
    </dl></section>;
  }
  const value = state as CadEntityChangeState;
  return <section className="change-evidence"><h4>{title}</h4><dl>
    <div><dt>HANDLE</dt><dd>{value.handle === null ? "none" : bounded(value.handle)}</dd></div>
    <div><dt>TYPE</dt><dd>{bounded(value.type)}</dd></div>
    <div><dt>LAYER</dt><dd>{bounded(value.layer)}</dd></div>
    <div><dt>BBOX</dt><dd>{formatBox(value.bbox)}</dd></div>
    <div><dt>TEXT</dt><dd>{value.text === null ? "none" : bounded(value.text)}</dd></div>
  </dl></section>;
}

function groupChanges(changes: CadChange[]) {
  const layer = changes.filter((change) => change.kind === "layer.create" || change.kind === "layer.update");
  const entity = changes.filter((change) => change.kind !== "layer.create" && change.kind !== "layer.update");
  return [
    { kind: "layer", label: "Layer changes", changes: layer },
    { kind: "entity", label: "Entity changes", changes: entity }
  ].filter((group) => group.changes.length > 0);
}

function formatBox(box: CadEntityChangeState["bbox"]) {
  return box ? `[${box.min.join(", ")}] → [${box.max.join(", ")}]` : "unavailable";
}

function bounded(value: string) {
  return value.length > 160 ? `${value.slice(0, 159)}…` : value;
}
