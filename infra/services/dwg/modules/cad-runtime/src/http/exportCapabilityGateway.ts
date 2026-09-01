import type { IncomingMessage, ServerResponse } from "node:http";

import {
  parseCadDrawingExportRequest,
  parseCadDrawingExportResponse,
  parseCadExportErrorResponse,
  parseCadOutputVerification,
  parseCadReportExportRequest,
  parseExportCapabilitiesResponse,
  type CadExportErrorCode,
  type ExportCapabilitiesResponse
} from "@dwg/contracts";
import { CadSaveError, type CadSaveErrorCode } from "@dwg/cad-capabilities";

import type { CadApplication } from "../application/createCadApplication.js";
import {
  drawingExportUnavailableReason,
  isDrawingExportAvailable
} from "../application/drawingExportPolicy.js";
import { CadReportDownloadStoreError } from "../application/reportDownloadStore.js";
import { handleDestinationGrantRequest } from "./destinationGrantGateway.js";

export interface ExportCapabilityRoutes {
  handle(request: IncomingMessage, response: ServerResponse, pathname: string, signal?: AbortSignal): Promise<boolean>;
}

function describeCapabilities(
  application: CadApplication
): ExportCapabilitiesResponse {
  const sourceFormat = application.activeDrawingFormat();
  const drawing = (format: "dxf" | "dwg") => ({
    format,
    kind: "drawing" as const,
    available: isDrawingExportAvailable(sourceFormat, format),
    reason: drawingExportUnavailableReason(sourceFormat, format)
  });
  return parseExportCapabilitiesResponse({
    capabilities: [
      { format: "json", kind: "report", available: true, reason: null },
      { format: "csv", kind: "report", available: true, reason: null },
      { format: "pdf", kind: "report", available: true, reason: null },
      { format: "svg", kind: "report", available: true, reason: null },
      drawing("dxf"),
      drawing("dwg")
    ]
  });
}
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_BODY_BYTES = 64 * 1024;

export function createExportCapabilityRoutes(
  application: CadApplication
): ExportCapabilityRoutes {
  return {
    async handle(request, response, pathname, signal) {
      try {
      if (request.method === "GET" && pathname === "/api/export/capabilities") {
        sendJson(response, 200, describeCapabilities(application));
        return true;
      }
      if (request.method === "POST" && pathname === "/api/export/destination-grants") {
        return handleDestinationGrantRequest(request, response, application, readJsonBody, signal);
      }
      if (request.method === "POST" && pathname === "/api/export/reports") {
        const input = parseCadReportExportRequest(await readJsonBody(request));
        sendJson(response, 200, await application.createReportDownload(input, signal));
        return true;
      }
      if (request.method === "GET" && pathname.startsWith("/api/export/reports/")) {
        const id = pathname.slice("/api/export/reports/".length);
        const download = uuidPattern.test(id) ? application.consumeReportDownload(id) : null;
        if (!download) {
          sendExportError(response, 404, "REPORT_DOWNLOAD_UNKNOWN", "Report download is unknown or expired.");
          return true;
        }
        response.statusCode = 200;
        response.setHeader("content-type", download.mediaType);
        response.setHeader("content-disposition", `attachment; filename="${download.filename}"`);
        response.setHeader("content-length", String(download.bytes.byteLength));
        response.end(Buffer.from(download.bytes));
        return true;
      }
      if (request.method === "POST" && pathname === "/api/export/drawings") {
        const input = parseCadDrawingExportRequest(await readJsonBody(request));
        const verification = parseCadOutputVerification(
          await application.capabilities.execute("export.drawing", input, signal)
        );
        sendJson(response, 200, parseCadDrawingExportResponse({
          verificationId: verification.id,
          status: verification.status
        }));
        return true;
      }
      if (request.method === "GET" && pathname.startsWith("/api/export/verifications/")) {
        const id = pathname.slice("/api/export/verifications/".length);
        if (!uuidPattern.test(id)) {
          sendExportError(response, 400, "VERIFICATION_REQUEST_INVALID", "Invalid verification request.");
          return true;
        }
        const verification = await application.capabilities.execute("verification.get", { id }, signal);
        if (!verification) {
          sendExportError(response, 404, "VERIFICATION_UNKNOWN", "Export verification is unknown.");
        } else {
          sendJson(response, 200, { verification: parseCadOutputVerification(verification) });
        }
        return true;
      }
      return false;
      } catch (error) {
        if (!isExportRoute(pathname)) throw error;
        const failure = toExportGatewayFailure(error);
        sendJson(response, failure.status, parseCadExportErrorResponse({
          error: {
            code: failure.code,
            message: failure.message
          }
        }));
        return true;
      }
    }
  };
}

function isExportRoute(pathname: string): boolean {
  return pathname === "/api/export/capabilities" ||
    pathname === "/api/export/destination-grants" ||
    pathname === "/api/export/reports" ||
    pathname === "/api/export/drawings" ||
    pathname.startsWith("/api/export/reports/") ||
    pathname.startsWith("/api/export/verifications/");
}

function toExportGatewayFailure(error: unknown): {
  status: number;
  code: CadExportErrorCode;
  message: string;
} {
  if (error instanceof CadReportDownloadStoreError) {
    return {
      status: 503,
      code: "REPORT_DOWNLOAD_CAPACITY",
      message: "Report download capacity is temporarily unavailable."
    };
  }
  if (error instanceof CadSaveError) return mapCadSaveError(error.code);
  return {
    status: isRequestError(error) ? 400 : 500,
    code: isRequestError(error) ? "EXPORT_REQUEST_INVALID" : "EXPORT_FAILED",
    message: isRequestError(error)
      ? "Invalid export request."
      : "Export operation failed."
  };
}

function mapCadSaveError(code: CadSaveErrorCode): {
  status: number;
  code: CadExportErrorCode;
  message: string;
} {
  switch (code) {
    case "CAD_SAVE_OUTPUT_EXISTS":
      return { status: 409, code: "OUTPUT_ALREADY_EXISTS", message: "An output with that filename already exists." };
    case "DESTINATION_GRANT_UNKNOWN":
      return { status: 404, code, message: "Destination grant is unknown." };
    case "DESTINATION_GRANT_EXPIRED":
      return { status: 410, code, message: "Destination grant has expired." };
    case "DESTINATION_GRANT_REUSED":
      return { status: 409, code, message: "Destination grant has already been used." };
    case "DESTINATION_GRANT_INVALID":
      return { status: 400, code, message: "Destination grant is invalid." };
    case "CAD_SAVE_STALE":
      return { status: 409, code: "REVISION_STALE", message: "Drawing revision is stale." };
    case "CAD_SAVE_DESTINATION_UNSUPPORTED":
      return { status: 409, code: "EXPORT_UNSUPPORTED", message: "Drawing export is unavailable." };
    case "CAD_SAVE_INPUT_INVALID":
    case "CAD_SAVE_DESTINATION_INVALID":
    case "CAD_SAVE_SOURCE_OUTPUT_EQUAL":
      return { status: 400, code: "EXPORT_REQUEST_INVALID", message: "Invalid drawing export request." };
    default:
      return { status: 500, code: "EXPORT_FAILED", message: "Drawing export failed." };
  }
}

function isRequestError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : "";
  return /(?:_REQUEST_INVALID|_INPUT_INVALID|REQUEST_TOO_LARGE|Unexpected end of JSON|JSON)/u.test(message);
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of request) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += value.byteLength;
    if (bytes > MAX_BODY_BYTES) throw new Error("EXPORT_REQUEST_TOO_LARGE");
    chunks.push(value);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  if (response.destroyed || response.writableEnded) return;
  response.statusCode = status;
  response.setHeader("content-type", "application/json; charset=utf-8");
  response.end(JSON.stringify(value));
}

function sendExportError(
  response: ServerResponse,
  status: number,
  code: CadExportErrorCode,
  message: string
): void {
  sendJson(response, status, parseCadExportErrorResponse({
    error: { code, message }
  }));
}
