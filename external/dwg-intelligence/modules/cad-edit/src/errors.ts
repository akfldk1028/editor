export type CadEditErrorCode =
  | "EDIT_DOCUMENT_MISMATCH"
  | "EDIT_REVISION_CONFLICT"
  | "EDIT_PRECONDITION_FAILED"
  | "EDIT_PRECONDITION_SCOPE"
  | "EDIT_PRECONDITION_COVERAGE"
  | "EDIT_DUPLICATE_TARGET"
  | "EDIT_COPY_ID_COLLISION"
  | "EDIT_TARGET_NOT_FOUND"
  | "EDIT_UNSUPPORTED_ENTITY"
  | "EDIT_LAYER_EXISTS"
  | "EDIT_REVISION_LIMIT"
  | "EDIT_PREVIEW_INVALID"
  | "EDIT_DUPLICATE_TRANSACTION"
  | "EDIT_UNDO_UNAVAILABLE"
  | "EDIT_REDO_UNAVAILABLE"
  | "EDIT_LINEAGE_LIMIT_REACHED";

export class CadEditError extends Error {
  readonly code: CadEditErrorCode;

  constructor(code: CadEditErrorCode, message: string) {
    super(message);
    this.name = "CadEditError";
    this.code = code;
  }
}
