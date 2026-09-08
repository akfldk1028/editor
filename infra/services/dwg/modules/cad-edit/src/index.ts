export { previewEditBatch, type CadEditPreview } from "./applyBatch.js";
export { CadEditError, type CadEditErrorCode } from "./errors.js";
export {
  createCadEditHistory,
  type CadCommittedTransaction,
  type CadCommittedTransactionStore,
  type CadEditHistory,
  type CadHistoryTransition,
  type CadHistoryEntry,
  type CadSaveState
} from "./history.js";
