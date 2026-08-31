import {
  parseCadDrawingExportResponse,
  parseCadReportExportResponse,
  parseDestinationGrantResponse,
  parseExportCapabilitiesResponse,
  type CadDrawingExportRequest,
  type CadDrawingExportResponse,
  type CadReportExportRequest,
  type CadReportExportResponse,
  type DestinationGrantResponse,
  type ExportCapabilitiesResponse
} from "@dwg/contracts";

import { getJson, postJson } from "./httpClient";

export function loadExportCapabilities(signal?: AbortSignal): Promise<ExportCapabilitiesResponse> {
  return getJson("/api/export/capabilities", signal, isExportCapabilitiesResponse);
}

export function requestExportDestination(signal?: AbortSignal): Promise<DestinationGrantResponse> {
  return postJson("/api/export/destination-grants", {}, signal, validates(parseDestinationGrantResponse));
}

export function exportReport(
  request: CadReportExportRequest,
  signal?: AbortSignal
): Promise<CadReportExportResponse> {
  return postJson("/api/export/reports", request, signal, validates(parseCadReportExportResponse));
}

export function exportDrawing(
  request: CadDrawingExportRequest,
  signal?: AbortSignal
): Promise<CadDrawingExportResponse> {
  return postJson("/api/export/drawings", request, signal, validates(parseCadDrawingExportResponse));
}

export function reportDownloadUrl(downloadId: string): string {
  return `/api/export/reports/${encodeURIComponent(downloadId)}`;
}

function isExportCapabilitiesResponse(value: unknown): value is ExportCapabilitiesResponse {
  try {
    parseExportCapabilitiesResponse(value);
    return true;
  } catch {
    return false;
  }
}

function validates<T>(parser: (value: unknown) => T) {
  return (value: unknown): value is T => {
    try {
      parser(value);
      return true;
    } catch {
      return false;
    }
  };
}
