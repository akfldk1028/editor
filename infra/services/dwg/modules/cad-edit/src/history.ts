import type {
  CadChange,
  CadEditBatch,
  CadResolvedCommand
} from "@dwg/contracts";
import {
  cloneDocumentSnapshot,
  type CadDocumentSnapshot
} from "@dwg/cad-document";
import { previewEditBatch, type CadEditPreview } from "./applyBatch.js";
import { CadEditError } from "./errors.js";

const DEFAULT_HISTORY_LIMIT = 100;
const MAX_ACTIVE_LINEAGE_COMMANDS = 10_000;

export interface CadHistoryEntry {
  transactionId: string;
  batch: CadEditBatch;
  beforeRevision: number;
  afterRevision: number;
  changeCount: number;
}

export interface CadCommittedTransaction {
  status: "applied" | "undone" | "superseded";
  batch: CadEditBatch;
  before: CadDocumentSnapshot;
  after: CadDocumentSnapshot;
  resolvedCommands: CadResolvedCommand[];
  changes: CadChange[];
}

export interface CadCommittedTransactionStore {
  getCommittedTransaction(transactionId: string): CadCommittedTransaction | null;
  getSaveState(documentId: string, expectedRevision: number): CadSaveState | null;
}

export interface CadSaveState {
  documentId: string;
  revision: number;
  source: CadDocumentSnapshot;
  current: CadDocumentSnapshot;
  lineage: readonly CadCommittedTransaction[];
}

export interface CadHistoryTransition {
  current: CadDocumentSnapshot;
  transaction: CadCommittedTransaction;
}

export interface CadEditHistory extends CadCommittedTransactionStore {
  current(): CadDocumentSnapshot;
  preview(batch: CadEditBatch): CadEditPreview;
  apply(preview: CadEditPreview): CadDocumentSnapshot;
  undo(expectedRevision: number): CadDocumentSnapshot;
  redo(expectedRevision: number): CadDocumentSnapshot;
  undoWithTransaction(expectedRevision: number): CadHistoryTransition;
  redoWithTransaction(expectedRevision: number): CadHistoryTransition;
  entries(): readonly CadHistoryEntry[];
}

interface StoredPreview {
  batch: CadEditBatch;
  preview: CadEditPreview;
}

interface InternalCommittedTransaction extends CadCommittedTransaction {
  status: CadCommittedTransaction["status"];
}

export function createCadEditHistory(
  initial: CadDocumentSnapshot,
  limit = DEFAULT_HISTORY_LIMIT
): CadEditHistory {
  if (!Number.isSafeInteger(limit) || limit < 0) {
    throw new RangeError("History limit must be a safe non-negative integer.");
  }

  const source = cloneDocumentSnapshot(initial);
  let current = cloneDocumentSnapshot(initial);
  const visibleEntries: CadHistoryEntry[] = [];
  const active: InternalCommittedTransaction[] = [];
  const redoStack: InternalCommittedTransaction[] = [];
  const transactions = new Map<string, InternalCommittedTransaction>();
  const previews = new WeakMap<CadEditPreview, StoredPreview>();

  function getCurrent(): CadDocumentSnapshot {
    return cloneDocumentSnapshot(current);
  }

  function preview(batch: CadEditBatch): CadEditPreview {
    const result = previewEditBatch(current, batch);
    rejectLineageOverflow(batch.commands.length);
    const stored: StoredPreview = {
      batch: structuredClone(batch),
      preview: clonePreview(result)
    };
    const returned = clonePreview(stored.preview);
    previews.set(returned, stored);
    return returned;
  }

  function apply(candidate: CadEditPreview): CadDocumentSnapshot {
    if (candidate.baseRevision !== current.revision || candidate.nextRevision !== current.revision + 1) {
      throw new CadEditError("EDIT_REVISION_CONFLICT", "Edit preview revision does not match the current document.");
    }
    const stored = previews.get(candidate);
    if (!stored) {
      throw new CadEditError("EDIT_PREVIEW_INVALID", "Edit preview was not created by this history.");
    }
    if (transactions.has(stored.batch.transactionId)) {
      throw new CadEditError("EDIT_DUPLICATE_TRANSACTION", "Edit transaction has already been committed.");
    }
    rejectLineageOverflow(stored.batch.commands.length);

    const before = cloneDocumentSnapshot(current);
    const after = cloneDocumentSnapshot(stored.preview.snapshot);
    if (after.revision !== before.revision + 1) {
      throw new CadEditError("EDIT_REVISION_CONFLICT", "Edit preview does not advance the document revision exactly once.");
    }

    const committed: InternalCommittedTransaction = {
      status: "applied",
      batch: structuredClone(stored.batch),
      before,
      after,
      resolvedCommands: structuredClone(stored.preview.resolvedCommands),
      changes: structuredClone(stored.preview.changes)
    };
    const visibleEntry = structuredClone({
      transactionId: committed.batch.transactionId,
      batch: committed.batch,
      beforeRevision: before.revision,
      afterRevision: after.revision,
      changeCount: committed.changes.length
    } satisfies CadHistoryEntry);
    const nextCurrent = cloneDocumentSnapshot(after);
    const result = cloneDocumentSnapshot(nextCurrent);

    for (const transaction of redoStack) transaction.status = "superseded";
    redoStack.length = 0;
    transactions.set(committed.batch.transactionId, committed);
    active.push(committed);
    appendVisibleEntry(visibleEntry);
    current = nextCurrent;
    previews.delete(candidate);
    return result;
  }

  function undo(expectedRevision: number): CadDocumentSnapshot {
    return undoWithTransaction(expectedRevision).current;
  }

  function undoWithTransaction(expectedRevision: number): CadHistoryTransition {
    requireCurrentRevision(expectedRevision);
    const transaction = active.at(-1);
    if (!transaction) {
      throw new CadEditError("EDIT_UNDO_UNAVAILABLE", "There is no applied edit transaction to undo.");
    }
    const restored = restoreWithNextRevision(transaction.before);
    active.pop();
    transaction.status = "undone";
    redoStack.push(transaction);
    current = restored;
    return {
      current: cloneDocumentSnapshot(restored),
      transaction: cloneCommittedTransaction(transaction)
    };
  }

  function redo(expectedRevision: number): CadDocumentSnapshot {
    return redoWithTransaction(expectedRevision).current;
  }

  function redoWithTransaction(expectedRevision: number): CadHistoryTransition {
    requireCurrentRevision(expectedRevision);
    const transaction = redoStack.at(-1);
    if (!transaction) {
      throw new CadEditError("EDIT_REDO_UNAVAILABLE", "There is no undone edit transaction to redo.");
    }
    const restored = restoreWithNextRevision(transaction.after);
    redoStack.pop();
    transaction.status = "applied";
    active.push(transaction);
    current = restored;
    return {
      current: cloneDocumentSnapshot(restored),
      transaction: cloneCommittedTransaction(transaction)
    };
  }

  function entries(): readonly CadHistoryEntry[] {
    return structuredClone(visibleEntries);
  }

  function getCommittedTransaction(transactionId: string): CadCommittedTransaction | null {
    const transaction = transactions.get(transactionId);
    return transaction ? cloneCommittedTransaction(transaction) : null;
  }

  function getSaveState(documentId: string, expectedRevision: number): CadSaveState | null {
    if (documentId !== current.documentId || expectedRevision !== current.revision) return null;
    if (source.documentId !== documentId || source.revision !== 0) return null;
    if (!isCompleteActiveLineage(source, active, current)) return null;
    return {
      documentId,
      revision: current.revision,
      source: cloneDocumentSnapshot(source),
      current: getCurrent(),
      lineage: active.map(cloneCommittedTransaction)
    };
  }

  function requireCurrentRevision(expectedRevision: number): void {
    if (expectedRevision !== current.revision) {
      throw new CadEditError("EDIT_REVISION_CONFLICT", "Expected revision does not match the current document.");
    }
  }

  function restoreWithNextRevision(content: CadDocumentSnapshot): CadDocumentSnapshot {
    const nextRevision = current.revision + 1;
    if (!Number.isSafeInteger(nextRevision)) {
      throw new CadEditError("EDIT_REVISION_LIMIT", "Next document revision exceeds the safe integer range.");
    }
    const restored = cloneDocumentSnapshot(content);
    restored.revision = nextRevision;
    return restored;
  }

  function rejectLineageOverflow(nextCommandCount: number): void {
    const commandCount = active.reduce((total, transaction) => total + transaction.batch.commands.length, 0);
    if (commandCount + nextCommandCount > MAX_ACTIVE_LINEAGE_COMMANDS) {
      throw new CadEditError(
        "EDIT_LINEAGE_LIMIT_REACHED",
        "Active edit lineage has reached its 10,000-command limit."
      );
    }
  }

  function appendVisibleEntry(entry: CadHistoryEntry): void {
    visibleEntries.push(entry);
    if (visibleEntries.length > limit) visibleEntries.splice(0, visibleEntries.length - limit);
  }

  return {
    current: getCurrent,
    preview,
    apply,
    undo,
    redo,
    undoWithTransaction,
    redoWithTransaction,
    entries,
    getCommittedTransaction,
    getSaveState
  };
}

function clonePreview(preview: CadEditPreview): CadEditPreview {
  return {
    transactionId: preview.transactionId,
    baseRevision: preview.baseRevision,
    nextRevision: preview.nextRevision,
    changes: structuredClone(preview.changes),
    resolvedCommands: structuredClone(preview.resolvedCommands),
    warnings: structuredClone(preview.warnings),
    snapshot: cloneDocumentSnapshot(preview.snapshot)
  };
}

function cloneCommittedTransaction(
  transaction: CadCommittedTransaction
): CadCommittedTransaction {
  return {
    status: transaction.status,
    batch: structuredClone(transaction.batch),
    before: cloneDocumentSnapshot(transaction.before),
    after: cloneDocumentSnapshot(transaction.after),
    resolvedCommands: structuredClone(transaction.resolvedCommands),
    changes: structuredClone(transaction.changes)
  };
}

function isCompleteActiveLineage(
  source: CadDocumentSnapshot,
  active: readonly CadCommittedTransaction[],
  current: CadDocumentSnapshot
): boolean {
  let predecessor = source;
  for (const transaction of active) {
    if (transaction.status !== "applied" || !sameDocumentContent(predecessor, transaction.before)) {
      return false;
    }
    predecessor = transaction.after;
  }
  return sameDocumentContent(predecessor, current);
}

function sameDocumentContent(left: CadDocumentSnapshot, right: CadDocumentSnapshot): boolean {
  const normalizedLeft = cloneDocumentSnapshot(left);
  const normalizedRight = cloneDocumentSnapshot(right);
  normalizedLeft.revision = 0;
  normalizedRight.revision = 0;
  return JSON.stringify(normalizedLeft) === JSON.stringify(normalizedRight);
}
