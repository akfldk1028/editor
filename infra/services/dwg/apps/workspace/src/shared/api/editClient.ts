import {
  parseCadEditApplyRequest,
  parseCadEditApplyResponse,
  parseCadEditBatch,
  parseCadEditHistoryRequest,
  parseCadEditErrorResponse,
  parseCadEditPreviewRequest,
  parseCadEditPreviewResponse,
  type CadEditApplyResponse,
  type CadEditBatch,
  type CadEditPreviewResponse
} from "@dwg/contracts";

export class EditClientError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly currentRevision: number | null = null
  ) {
    super(message);
    this.name = "EditClientError";
  }
}

export async function previewEdit(batch: CadEditBatch, signal?: AbortSignal): Promise<CadEditPreviewResponse> {
  const request = parseCadEditPreviewRequest({ batch: parseCadEditBatch(batch) });
  const result = await postEdit("/api/edit/preview", request, signal, parseCadEditPreviewResponse);
  if (
    result.documentId !== request.batch.documentId ||
    result.transactionId !== request.batch.transactionId ||
    result.baseRevision !== request.batch.expectedRevision
  ) {
    throw new EditClientError(
      "EDIT_PREVIEW_MISMATCH",
      "Preview response does not match proposal.",
    );
  }
  return result;
}

export async function applyEdit(
  previewId: string,
  documentId: string,
  expectedRevision: number,
  transactionId: string,
  expectedChangeCount: number,
  signal?: AbortSignal
): Promise<CadEditApplyResponse> {
  const request = parseCadEditApplyRequest({ previewId, documentId, expectedRevision, approved: true });
  const result = await postEdit("/api/edit/apply", request, signal, parseCadEditApplyResponse);
  requireCorrelatedResult(result, {
    documentId,
    transactionId,
    revision: expectedRevision + 1,
    changeCount: expectedChangeCount
  }, "EDIT_APPLY_MISMATCH", "Apply response does not match reviewed changes.");
  return result;
}

export async function undoEdit(
  documentId: string,
  expectedRevision: number,
  transactionId: string,
  expectedChangeCount: number,
  signal?: AbortSignal
): Promise<CadEditApplyResponse> {
  const request = parseCadEditHistoryRequest({ documentId, expectedRevision, approved: true });
  const result = await postEdit("/api/edit/undo", request, signal, parseCadEditApplyResponse);
  requireCorrelatedResult(result, {
    documentId,
    transactionId,
    revision: expectedRevision + 1,
    changeCount: expectedChangeCount
  }, "EDIT_HISTORY_MISMATCH", "History response does not match reviewed changes.");
  return result;
}

export async function redoEdit(
  documentId: string,
  expectedRevision: number,
  transactionId: string,
  expectedChangeCount: number,
  signal?: AbortSignal
): Promise<CadEditApplyResponse> {
  const request = parseCadEditHistoryRequest({ documentId, expectedRevision, approved: true });
  const result = await postEdit("/api/edit/redo", request, signal, parseCadEditApplyResponse);
  requireCorrelatedResult(result, {
    documentId,
    transactionId,
    revision: expectedRevision + 1,
    changeCount: expectedChangeCount
  }, "EDIT_HISTORY_MISMATCH", "History response does not match reviewed changes.");
  return result;
}

async function postEdit<T>(
  url: string,
  request: unknown,
  signal: AbortSignal | undefined,
  parse: (value: unknown) => T
): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
    signal
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new EditClientError("EDIT_RESPONSE_INVALID", `Invalid JSON response (HTTP ${response.status})`);
  }
  if (!response.ok) throw toEditClientError(payload, response.status);
  try {
    return parse(payload);
  } catch {
    throw new EditClientError("EDIT_RESPONSE_INVALID", "Response contract validation failed");
  }
}

function toEditClientError(payload: unknown, status: number): EditClientError {
  try {
    const { error } = parseCadEditErrorResponse(payload);
    return new EditClientError(
      error.code,
      error.message,
      "currentRevision" in error ? error.currentRevision : null
    );
  } catch {
    return new EditClientError("EDIT_REQUEST_FAILED", `HTTP ${status}`);
  }
}

function requireCorrelatedResult(
  result: CadEditApplyResponse,
  expected: CadEditApplyResponse,
  code: string,
  message: string
) {
  if (
    result.documentId !== expected.documentId ||
    result.transactionId !== expected.transactionId ||
    result.revision !== expected.revision ||
    result.changeCount !== expected.changeCount
  ) {
    throw new EditClientError(code, message);
  }
}
