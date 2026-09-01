import { parseCadEditBatch, type CadEditBatch } from "@dwg/contracts";

/** Browser composition seam for validated edit proposals; it never applies a CAD edit. */
export const CAD_EDIT_PROPOSAL_EVENT = "dwg:cad-edit-proposal/v1";

export function publishCadEditProposal(batch: CadEditBatch) {
  const detail = parseCadEditBatch(batch);
  window.dispatchEvent(new CustomEvent<CadEditBatch>(CAD_EDIT_PROPOSAL_EVENT, { detail }));
}

export function subscribeCadEditProposals(handlers: {
  onProposal(batch: CadEditBatch): void;
  onInvalid(): void;
}) {
  const listener = (event: Event) => {
    if (!(event instanceof CustomEvent)) {
      handlers.onInvalid();
      return;
    }
    try {
      handlers.onProposal(parseCadEditBatch(event.detail));
    } catch {
      handlers.onInvalid();
    }
  };
  window.addEventListener(CAD_EDIT_PROPOSAL_EVENT, listener);
  return () => window.removeEventListener(CAD_EDIT_PROPOSAL_EVENT, listener);
}
