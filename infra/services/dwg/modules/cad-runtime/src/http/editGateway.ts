import type { IncomingMessage, ServerResponse } from "node:http";

import {
  parseCadEditApplyRequest,
  parseCadEditApplyResponse,
  parseCadEditHistoryRequest,
  parseCadEditPreviewRequest,
  parseCadEditPreviewResponse,
  parseCadEditErrorResponse,
  type CadEditApplyResponse,
  type CadEditPreviewResponse
} from "@dwg/contracts";
import type { CadCapabilityName, CadCapabilityRuntime } from "@dwg/cad-capabilities";

export const MAX_EDIT_REQUEST_BYTES = 1024 * 1024;

type EditCapabilityName = Extract<CadCapabilityName, `edit.${string}`>;

export interface EditGatewayDependencies {
  execute(name: EditCapabilityName, input: unknown, signal?: AbortSignal): Promise<unknown>;
}

export async function handleEditGatewayRequest(
  request: IncomingMessage,
  response: ServerResponse,
  pathname: string,
  dependencies: EditGatewayDependencies,
  signal: AbortSignal
): Promise<boolean> {
  const operation = operationFor(pathname);
  if (!operation || request.method !== "POST") return false;

  try {
    const body = await readEditJsonBody(request);
    const input = parseRequest(operation, body);
    const result = await dependencies.execute(operation, input, signal);
    sendJson(response, 200, parseResponse(operation, result));
  } catch (error) {
    const failure = toEditGatewayFailure(error);
    sendJson(response, failure.status, parseCadEditErrorResponse({
      error: {
        code: failure.code,
        message: failure.message,
        ...(failure.currentRevision === null ? {} : { currentRevision: failure.currentRevision })
      }
    }));
  }
  return true;
}

function operationFor(pathname: string): EditCapabilityName | null {
  switch (pathname) {
    case "/api/edit/preview": return "edit.preview";
    case "/api/edit/apply": return "edit.apply";
    case "/api/edit/undo": return "edit.undo";
    case "/api/edit/redo": return "edit.redo";
    default: return null;
  }
}

function parseRequest(operation: EditCapabilityName, value: unknown): unknown {
  switch (operation) {
    case "edit.preview": return parseCadEditPreviewRequest(value);
    case "edit.apply": return parseCadEditApplyRequest(value);
    case "edit.undo":
    case "edit.redo": return parseCadEditHistoryRequest(value);
  }
}

function parseResponse(
  operation: EditCapabilityName,
  value: unknown
): CadEditPreviewResponse | CadEditApplyResponse {
  try {
    return operation === "edit.preview"
      ? parseCadEditPreviewResponse(value)
      : parseCadEditApplyResponse(value);
  } catch {
    throw new EditGatewayError(
      500,
      "EDIT_RESPONSE_INVALID",
      "CAD edit capability returned an invalid response."
    );
  }
}

function readEditJsonBody(request: IncomingMessage): Promise<unknown> {
  const declaredLength = Number(request.headers["content-length"] ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > MAX_EDIT_REQUEST_BYTES) {
    request.resume();
    return Promise.reject(new EditGatewayError(
      413,
      "EDIT_REQUEST_TOO_LARGE",
      "CAD edit request exceeds the 1 MiB limit."
    ));
  }

  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    let settled = false;
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      request.resume();
      reject(error);
    };
    request.on("aborted", () => fail(new EditGatewayError(499, "EDIT_REQUEST_ABORTED", "CAD edit request was cancelled.")));
    request.on("error", () => fail(new EditGatewayError(400, "EDIT_REQUEST_INVALID", "Invalid CAD edit request.")));
    request.on("data", (chunk: Buffer) => {
      if (settled) return;
      size += chunk.length;
      if (size > MAX_EDIT_REQUEST_BYTES) {
        fail(new EditGatewayError(413, "EDIT_REQUEST_TOO_LARGE", "CAD edit request exceeds the 1 MiB limit."));
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (settled) return;
      settled = true;
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new EditGatewayError(400, "EDIT_REQUEST_INVALID", "Invalid CAD edit request."));
      }
    });
  });
}

class EditGatewayError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly publicMessage: string,
    readonly currentRevision: number | null = null
  ) {
    super(publicMessage);
  }
}

function toEditGatewayFailure(error: unknown): EditGatewayError {
  if (error instanceof EditGatewayError) return error;
  const code = typeof error === "object" && error !== null && "code" in error
    ? (error as { code?: unknown }).code
    : undefined;
  if (typeof code === "string" && /^EDIT_[A-Z0-9_]{1,60}$/.test(code)) {
    if (code === "EDIT_PREVIEW_STALE") {
      const currentRevision = typeof error === "object" && error !== null && "currentRevision" in error
        ? (error as { currentRevision?: unknown }).currentRevision
        : undefined;
      if (
        typeof currentRevision !== "number" ||
        !Number.isSafeInteger(currentRevision) ||
        currentRevision < 0
      ) {
        return new EditGatewayError(
          500,
          "EDIT_RESPONSE_INVALID",
          "CAD edit capability returned an invalid response."
        );
      }
      return new EditGatewayError(
        409,
        code,
        "CAD edit operation could not be completed.",
        currentRevision
      );
    }
    return new EditGatewayError(409, code, "CAD edit operation could not be completed.");
  }
  return new EditGatewayError(400, "EDIT_REQUEST_INVALID", "Invalid CAD edit request.");
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  if (response.destroyed || response.writableEnded) return;
  response.statusCode = status;
  response.end(JSON.stringify(value));
}
