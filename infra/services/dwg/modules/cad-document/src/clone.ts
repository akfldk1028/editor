import type { CadDocumentSnapshot } from "./snapshot.js";

export function cloneDocumentSnapshot(
  snapshot: CadDocumentSnapshot
): CadDocumentSnapshot {
  return structuredClone(snapshot);
}
