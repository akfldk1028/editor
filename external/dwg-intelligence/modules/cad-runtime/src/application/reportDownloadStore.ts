import { randomUUID } from "node:crypto";

import type { ExportedReport } from "@dwg/cad-export";
import {
  parseCadReportExportRequest,
  parseCadReportExportResponse,
  type CadReportExportResponse
} from "@dwg/contracts";

export const MAX_REPORT_DOWNLOAD_ENTRIES = 64;
export const MAX_REPORT_DOWNLOAD_BYTES = 16 * 1024 * 1024;
const REPORT_DOWNLOAD_TTL_MS = 10 * 60 * 1000;

interface StoredReport extends ExportedReport {
  expiresAt: number;
}

export class CadReportDownloadStoreError extends Error {
  constructor(readonly code: "REPORT_DOWNLOAD_CAPACITY") {
    super("CAD report download capacity is temporarily unavailable.");
    this.name = "CadReportDownloadStoreError";
  }
}

export interface CadReportDownloadStore {
  create(input: unknown, signal?: AbortSignal): Promise<CadReportExportResponse>;
  consume(id: string): ExportedReport | null;
}

export function createCadReportDownloadStore(options: {
  generate(input: unknown, signal?: AbortSignal): Promise<unknown>;
  clock?: () => number;
}): CadReportDownloadStore {
  const clock = options.clock ?? Date.now;
  const reports = new Map<string, StoredReport>();
  let totalBytes = 0;

  function pruneExpired(now: number): void {
    for (const [id, report] of reports) {
      if (report.expiresAt <= now) remove(id, report);
    }
  }

  function remove(id: string, report: StoredReport): void {
    if (!reports.delete(id)) return;
    totalBytes -= report.bytes.byteLength;
  }

  return {
    async create(input, signal) {
      const request = parseCadReportExportRequest(input);
      const report = asExportedReport(await options.generate(request, signal));
      const now = clock();
      pruneExpired(now);
      if (
        reports.size >= MAX_REPORT_DOWNLOAD_ENTRIES ||
        report.bytes.byteLength > MAX_REPORT_DOWNLOAD_BYTES - totalBytes
      ) {
        throw new CadReportDownloadStoreError("REPORT_DOWNLOAD_CAPACITY");
      }
      const downloadId = randomUUID();
      const stored: StoredReport = {
        ...report,
        bytes: report.bytes.slice(),
        expiresAt: now + REPORT_DOWNLOAD_TTL_MS
      };
      reports.set(downloadId, stored);
      totalBytes += stored.bytes.byteLength;
      return parseCadReportExportResponse({
        downloadId,
        filename: stored.filename,
        mediaType: stored.mediaType,
        sha256: stored.sha256
      });
    },
    consume(id) {
      const now = clock();
      pruneExpired(now);
      const report = reports.get(id);
      if (!report) return null;
      remove(id, report);
      return {
        format: report.format,
        mediaType: report.mediaType,
        filename: report.filename,
        bytes: report.bytes.slice(),
        sha256: report.sha256
      };
    }
  };
}

function asExportedReport(value: unknown): ExportedReport {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    throw new Error("CAD_REPORT_EXPORT_RESULT_INVALID");
  }
  const report = value as Partial<ExportedReport>;
  if (
    !["json", "csv", "pdf", "svg"].includes(report.format ?? "") ||
    typeof report.mediaType !== "string" ||
    typeof report.filename !== "string" ||
    !(report.bytes instanceof Uint8Array) ||
    typeof report.sha256 !== "string"
  ) {
    throw new Error("CAD_REPORT_EXPORT_RESULT_INVALID");
  }
  return report as ExportedReport;
}
