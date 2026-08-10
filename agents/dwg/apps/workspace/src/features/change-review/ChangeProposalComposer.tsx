import { useState } from "react";

import { parseCadEditBatch, type CadEntityIndexItem } from "@dwg/contracts";

import { publishCadEditProposal } from "../../shared/cadEditProposalInbox";

interface Props {
  documentId: string;
  expectedRevision: number;
  selectedEntity: CadEntityIndexItem | null;
  disabled: boolean;
}

export function ChangeProposalComposer({ documentId, expectedRevision, selectedEntity, disabled }: Props) {
  const [delta, setDelta] = useState({ x: "0", y: "0", z: "0" });
  const [error, setError] = useState<string | null>(null);
  const handle = selectedEntity?.handle ?? null;

  function proposeMove() {
    if (!selectedEntity || !handle) {
      setError("Select an entity with a grounded handle first.");
      return;
    }
    const movement: [number, number, number] = [
      Number(delta.x),
      Number(delta.y),
      Number(delta.z)
    ];
    if (!movement.every(Number.isFinite) || movement.every((value) => value === 0)) {
      setError("Enter a finite non-zero move.");
      return;
    }
    try {
      const batch = parseCadEditBatch({
        schemaVersion: "cad-edit/v1",
        transactionId: crypto.randomUUID(),
        documentId,
        expectedRevision,
        commands: [{
          commandId: crypto.randomUUID(),
          expectedRevision,
          origin: { kind: "user", id: "workspace-change-review" },
          preconditions: [
            { target: handle, field: "type", equals: selectedEntity.type },
            { target: handle, field: "layer", equals: selectedEntity.layer }
          ],
          operation: { kind: "entity.move", handles: [handle], delta: movement }
        }]
      });
      publishCadEditProposal(batch);
      setError(null);
    } catch {
      setError("Unable to create a valid CAD edit proposal.");
    }
  }

  return (
    <section aria-label="Create change proposal" className="change-proposal-composer">
      <header>
        <strong>Move proposal</strong>
        <span>{handle ? `Selected handle ${bounded(handle)}` : "Select a grounded entity in Findings."}</span>
      </header>
      <div className="change-proposal-fields">
        <label>Move X<input aria-label="Move X" disabled={disabled} inputMode="decimal" onChange={(event) => setDelta((current) => ({ ...current, x: event.target.value }))} value={delta.x} /></label>
        <label>Move Y<input aria-label="Move Y" disabled={disabled} inputMode="decimal" onChange={(event) => setDelta((current) => ({ ...current, y: event.target.value }))} value={delta.y} /></label>
        <label>Move Z<input aria-label="Move Z" disabled={disabled} inputMode="decimal" onChange={(event) => setDelta((current) => ({ ...current, z: event.target.value }))} value={delta.z} /></label>
        <button disabled={!handle || disabled} onClick={proposeMove} type="button">Preview move</button>
      </div>
      {error && <div className="change-proposal-error" role="alert">{error}</div>}
    </section>
  );
}

function bounded(value: string) {
  return value.length > 80 ? `${value.slice(0, 79)}…` : value;
}
