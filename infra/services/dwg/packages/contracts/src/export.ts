export const REPORT_FORMATS = ["json", "csv", "pdf", "svg"] as const;
export const DRAWING_FORMATS = ["dxf", "dwg"] as const;

export type ReportFormat = (typeof REPORT_FORMATS)[number];
export type DrawingFormat = (typeof DRAWING_FORMATS)[number];
export type ExportFormat = ReportFormat | DrawingFormat;
export type ExportKind = "report" | "drawing";

export const MAX_CAD_OUTPUT_VERIFICATION_ID_CHARS = 256;
export const MAX_CAD_OUTPUT_VERIFICATION_VERSION_CHARS = 128;
export const MAX_CAD_OUTPUT_VERIFICATION_HANDLE_MAP_ENTRIES = 10_000;
export const MAX_CAD_OUTPUT_VERIFICATION_WARNINGS = 100;
export const MAX_CAD_OUTPUT_VERIFICATION_WARNING_CHARS = 512;

/** Serializable proof that a generated drawing was independently verified. */
export interface CadOutputVerification {
  id: string;
  status: "passed" | "failed";
  format: DrawingFormat;
  version: string;
  sourceSha256: string;
  outputSha256: string;
  intendedChangeCount: number;
  verifiedChangeCount: number;
  copiedHandleMap: Record<string, string>;
  warnings: string[];
}

export interface ExportCapabilityItem {
  format: ExportFormat;
  kind: ExportKind;
  available: boolean;
  reason: string | null;
}

export interface ExportCapabilitiesResponse {
  capabilities: ExportCapabilityItem[];
}

export interface DestinationGrantRequest {}
export interface DestinationGrantResponse {
  grantId: string;
  displayDirectory: string;
  expiresAt: number;
}
export interface CadReportExportRequest {
  documentId: string;
  revision: number;
  format: ReportFormat;
}
export interface CadReportExportResponse {
  downloadId: string;
  filename: string;
  mediaType: string;
  sha256: string;
}
export interface CadDrawingExportRequest {
  documentId: string;
  expectedRevision: number;
  destinationGrantId: string;
  baseFilename: string;
  format: DrawingFormat;
  version: string;
}
export interface CadDrawingExportResponse {
  verificationId: string;
  status: "passed" | "failed";
}
export interface CadVerificationResponse {
  verification: CadOutputVerification;
}
export const CAD_EXPORT_ERROR_CODES = [
  "EXPORT_REQUEST_INVALID",
  "REPORT_DOWNLOAD_CAPACITY",
  "REPORT_DOWNLOAD_UNKNOWN",
  "OUTPUT_ALREADY_EXISTS",
  "DESTINATION_GRANT_UNKNOWN",
  "DESTINATION_GRANT_EXPIRED",
  "DESTINATION_GRANT_REUSED",
  "DESTINATION_GRANT_INVALID",
  "DESTINATION_SELECTION_CANCELLED",
  "REVISION_STALE",
  "VERIFICATION_REQUEST_INVALID",
  "VERIFICATION_UNKNOWN",
  "EXPORT_UNSUPPORTED",
  "EXPORT_FAILED"
] as const;
export type CadExportErrorCode = (typeof CAD_EXPORT_ERROR_CODES)[number];
export interface CadExportErrorResponse {
  error: {
    code: CadExportErrorCode;
    message: string;
  };
}

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const versionPattern = /^AC[0-9]{4}$/u;

export function parseDestinationGrantRequest(value: unknown): DestinationGrantRequest {
  const object = exportRecord(value, "DESTINATION_GRANT_REQUEST_INVALID");
  requireExportExactKeys(object, [], "DESTINATION_GRANT_REQUEST_INVALID");
  return {};
}

export function parseDestinationGrantResponse(value: unknown): DestinationGrantResponse {
  const object = exportRecord(value, "DESTINATION_GRANT_RESPONSE_INVALID");
  requireExportExactKeys(object, ["grantId", "displayDirectory", "expiresAt"], "DESTINATION_GRANT_RESPONSE_INVALID");
  if (!isUuid(object.grantId) || !isBoundedString(object.displayDirectory, 512) ||
      !Number.isSafeInteger(object.expiresAt) || (object.expiresAt as number) < 0) {
    throw new Error("DESTINATION_GRANT_RESPONSE_INVALID");
  }
  return object as unknown as DestinationGrantResponse;
}

export function parseCadReportExportRequest(value: unknown): CadReportExportRequest {
  const object = exportRecord(value, "CAD_REPORT_EXPORT_REQUEST_INVALID");
  requireExportExactKeys(object, ["documentId", "revision", "format"], "CAD_REPORT_EXPORT_REQUEST_INVALID");
  if (!isBoundedString(object.documentId, 512) || !isSafeCount(object.revision) ||
      !REPORT_FORMATS.includes(object.format as ReportFormat)) {
    throw new Error("CAD_REPORT_EXPORT_REQUEST_INVALID");
  }
  return object as unknown as CadReportExportRequest;
}

export function parseCadReportExportResponse(value: unknown): CadReportExportResponse {
  const object = exportRecord(value, "CAD_REPORT_EXPORT_RESPONSE_INVALID");
  requireExportExactKeys(object, ["downloadId", "filename", "mediaType", "sha256"], "CAD_REPORT_EXPORT_RESPONSE_INVALID");
  if (!isUuid(object.downloadId) || !isSafeFilename(object.filename) ||
      !isBoundedString(object.mediaType, 128) || !isSha256(object.sha256)) {
    throw new Error("CAD_REPORT_EXPORT_RESPONSE_INVALID");
  }
  return {
    ...(object as unknown as CadReportExportResponse),
    sha256: (object.sha256 as string).toUpperCase()
  };
}

export function parseCadDrawingExportRequest(value: unknown): CadDrawingExportRequest {
  const object = exportRecord(value, "CAD_DRAWING_EXPORT_REQUEST_INVALID");
  requireExportExactKeys(object, ["documentId", "expectedRevision", "destinationGrantId", "baseFilename", "format", "version"], "CAD_DRAWING_EXPORT_REQUEST_INVALID");
  if (!isBoundedString(object.documentId, 512) || !isSafeCount(object.expectedRevision) ||
      !isUuid(object.destinationGrantId) || !isSafeFilename(object.baseFilename) ||
      !DRAWING_FORMATS.includes(object.format as DrawingFormat) ||
      typeof object.version !== "string" || !versionPattern.test(object.version)) {
    throw new Error("CAD_DRAWING_EXPORT_REQUEST_INVALID");
  }
  return object as unknown as CadDrawingExportRequest;
}

export function parseCadDrawingExportResponse(value: unknown): CadDrawingExportResponse {
  const object = exportRecord(value, "CAD_DRAWING_EXPORT_RESPONSE_INVALID");
  requireExportExactKeys(object, ["verificationId", "status"], "CAD_DRAWING_EXPORT_RESPONSE_INVALID");
  if (!isUuid(object.verificationId) || (object.status !== "passed" && object.status !== "failed")) {
    throw new Error("CAD_DRAWING_EXPORT_RESPONSE_INVALID");
  }
  return object as unknown as CadDrawingExportResponse;
}

export function parseCadExportErrorResponse(value: unknown): CadExportErrorResponse {
  const object = exportRecord(value, "CAD_EXPORT_ERROR_RESPONSE_INVALID");
  requireExportExactKeys(object, ["error"], "CAD_EXPORT_ERROR_RESPONSE_INVALID");
  const error = exportRecord(object.error, "CAD_EXPORT_ERROR_RESPONSE_INVALID");
  requireExportExactKeys(error, ["code", "message"], "CAD_EXPORT_ERROR_RESPONSE_INVALID");
  if (
    !CAD_EXPORT_ERROR_CODES.includes(error.code as CadExportErrorCode) ||
    !isBoundedString(error.message, 256)
  ) {
    throw new Error("CAD_EXPORT_ERROR_RESPONSE_INVALID");
  }
  return {
    error: {
      code: error.code as CadExportErrorCode,
      message: error.message
    }
  };
}

export function parseCadVerificationResponse(value: unknown): CadVerificationResponse {
  const object = exportRecord(value, "CAD_VERIFICATION_RESPONSE_INVALID");
  requireExportExactKeys(object, ["verification"], "CAD_VERIFICATION_RESPONSE_INVALID");
  return { verification: parseCadOutputVerification(object.verification) };
}

const formats = new Set<ExportFormat>([...REPORT_FORMATS, ...DRAWING_FORMATS]);
const exportKinds = new Set<ExportKind>(["report", "drawing"]);

export function parseExportCapabilitiesResponse(value: unknown): ExportCapabilitiesResponse {
  const object = record(value);
  requireExactKeys(object, ["capabilities"]);
  if (!Array.isArray(object.capabilities) || object.capabilities.length !== formats.size) {
    throw new Error("EXPORT_CAPABILITIES_RESPONSE_INVALID");
  }
  const capabilities = object.capabilities.map(parseExportCapabilityItem);
  if (new Set(capabilities.map((item) => item.format)).size !== formats.size) {
    throw new Error("EXPORT_CAPABILITIES_RESPONSE_INVALID");
  }
  return { capabilities };
}

export function parseExportCapabilityItem(value: unknown): ExportCapabilityItem {
  const object = record(value);
  requireExactKeys(object, ["format", "kind", "available", "reason"]);
  if (!formats.has(object.format as ExportFormat) || !exportKinds.has(object.kind as ExportKind)) {
    throw new Error("EXPORT_CAPABILITY_ITEM_INVALID");
  }
  const format = object.format as ExportFormat;
  const kind = object.kind as ExportKind;
  if ((REPORT_FORMATS.includes(format as ReportFormat) ? "report" : "drawing") !== kind) {
    throw new Error("EXPORT_CAPABILITY_ITEM_INVALID");
  }
  if (typeof object.available !== "boolean") {
    throw new Error("EXPORT_CAPABILITY_ITEM_INVALID");
  }
  const reasonValid = object.available
    ? object.reason === null
    : typeof object.reason === "string" &&
      object.reason.trim().length > 0 &&
      object.reason.length <= 128;
  if (!reasonValid) {
    throw new Error("EXPORT_CAPABILITY_ITEM_INVALID");
  }
  return { format, kind, available: object.available, reason: object.reason as string | null };
}

export function parseCadOutputVerification(value: unknown): CadOutputVerification {
  const object = cadOutputRecord(value);
  const expectedKeys = [
    "id",
    "status",
    "format",
    "version",
    "sourceSha256",
    "outputSha256",
    "intendedChangeCount",
    "verifiedChangeCount",
    "copiedHandleMap",
    "warnings"
  ];
  if (
    !hasExactKeys(object, expectedKeys) ||
    !isBoundedString(object.id, MAX_CAD_OUTPUT_VERIFICATION_ID_CHARS) ||
    (object.status !== "passed" && object.status !== "failed") ||
    !DRAWING_FORMATS.includes(object.format as DrawingFormat) ||
    !isBoundedString(object.version, MAX_CAD_OUTPUT_VERIFICATION_VERSION_CHARS) ||
    !isSha256(object.sourceSha256) ||
    !isSha256(object.outputSha256) ||
    !isSafeCount(object.intendedChangeCount) ||
    !isSafeCount(object.verifiedChangeCount) ||
    !isBoundedHandleMap(object.copiedHandleMap) ||
    !isBoundedWarnings(object.warnings)
  ) {
    throw new Error("CAD_OUTPUT_VERIFICATION_INVALID");
  }

  return {
    id: object.id,
    status: object.status,
    format: object.format as DrawingFormat,
    version: object.version,
    sourceSha256: object.sourceSha256.toUpperCase(),
    outputSha256: object.outputSha256.toUpperCase(),
    intendedChangeCount: object.intendedChangeCount,
    verifiedChangeCount: object.verifiedChangeCount,
    copiedHandleMap: Object.fromEntries(
      Object.entries(object.copiedHandleMap).sort(([left], [right]) => compareText(left, right))
    ),
    warnings: [...object.warnings]
  };
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("EXPORT_CAPABILITIES_RESPONSE_INVALID");
  }
  return value as Record<string, unknown>;
}

function exportRecord(value: unknown, code: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(code);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) throw new Error(code);
  return value as Record<string, unknown>;
}

function requireExportExactKeys(value: Record<string, unknown>, expected: string[], code: string) {
  if (!hasExactKeys(value, expected)) throw new Error(code);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && uuidPattern.test(value);
}

function isSafeFilename(value: unknown): value is string {
  return isBoundedString(value, 255) && value === value.normalize("NFKC") &&
    !/[\\/:<>|?*\u0000-\u001f]/u.test(value) && value !== "." && value !== "..";
}

function cadOutputRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("CAD_OUTPUT_VERIFICATION_INVALID");
  }
  return value as Record<string, unknown>;
}

function requireExactKeys(value: Record<string, unknown>, expected: string[]) {
  if (!hasExactKeys(value, expected)) {
    throw new Error("EXPORT_CAPABILITIES_RESPONSE_INVALID");
  }
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const keys = Object.keys(value).sort();
  return keys.length === expected.length && keys.every((key, index) => key === [...expected].sort()[index]);
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/iu.test(value);
}

function isSafeCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isBoundedHandleMap(value: unknown): value is Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const entries = Object.entries(value);
  return (
    entries.length <= MAX_CAD_OUTPUT_VERIFICATION_HANDLE_MAP_ENTRIES &&
    entries.every(([key, mapped]) => isBoundedString(key, 256) && isBoundedString(mapped, 256))
  );
}

function isBoundedWarnings(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= MAX_CAD_OUTPUT_VERIFICATION_WARNINGS &&
    value.every((warning) => isBoundedString(warning, MAX_CAD_OUTPUT_VERIFICATION_WARNING_CHARS))
  );
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
