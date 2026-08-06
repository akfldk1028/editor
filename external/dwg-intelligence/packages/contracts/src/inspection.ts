import type { CadPointBox } from "./cad.js";

export const MAX_CAD_SEARCH_QUERY_CHARS = 128;

export type InspectionCheck =
  | { kind: "layer"; value: string }
  | { kind: "type"; value: string }
  | { kind: "text"; value: string; regex?: boolean };

export interface InspectionPayload {
  checks: InspectionCheck[];
}

export interface InspectionEvent {
  sequence: number;
  agentId:
    | "orchestrator"
    | "drawing-index-agent"
    | "search-agent"
    | "rule-check-agent"
    | "evidence-agent"
    | "viewer-agent"
    | "report-agent";
  action: string;
  status: "planned" | "completed" | "rejected";
}

export interface InspectionFinding {
  id: string;
  handle: string | null;
  type: string;
  layer: string;
  bbox: CadPointBox | null;
  text?: string | null;
  reason: string;
  confidence: number;
}

export type InspectionEvidenceField = "id" | "handle" | "type" | "layer" | "bbox";

export interface InspectionIssue {
  entityId: string;
  missing: InspectionEvidenceField[];
}

export interface InspectionRun {
  status: "completed" | "rejected";
  drawingId: string;
  events: InspectionEvent[];
  findings: InspectionFinding[];
  issues: InspectionIssue[];
  warnings: string[];
}

export function isInspectionPayload(value: unknown): value is InspectionPayload {
  if (!isRecord(value) || !hasOnlyKeys(value, ["checks"])) return false;
  if (!Array.isArray(value.checks) || value.checks.length < 1 || value.checks.length > 8) {
    return false;
  }
  return value.checks.every(isInspectionCheck);
}

export function isInspectionRun(value: unknown): value is InspectionRun {
  if (!isRecord(value)) return false;
  return (
    (value.status === "completed" || value.status === "rejected") &&
    typeof value.drawingId === "string" &&
    value.drawingId.length > 0 &&
    Array.isArray(value.events) &&
    value.events.every(isInspectionEvent) &&
    Array.isArray(value.findings) &&
    value.findings.every(isInspectionFinding) &&
    Array.isArray(value.issues) &&
    value.issues.every(isInspectionIssue) &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === "string")
  );
}

function isInspectionEvent(value: unknown): value is InspectionEvent {
  if (!isRecord(value)) return false;
  return (
    Number.isInteger(value.sequence) &&
    (value.sequence as number) >= 0 &&
    typeof value.agentId === "string" &&
    inspectionAgentIds.has(value.agentId) &&
    typeof value.action === "string" &&
    (
      value.status === "planned" ||
      value.status === "completed" ||
      value.status === "rejected"
    )
  );
}

function isInspectionFinding(value: unknown): value is InspectionFinding {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    (typeof value.handle === "string" || value.handle === null) &&
    typeof value.type === "string" &&
    typeof value.layer === "string" &&
    (value.bbox === null || isPointBox(value.bbox)) &&
    (
      value.text === undefined ||
      typeof value.text === "string" ||
      value.text === null
    ) &&
    typeof value.reason === "string" &&
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    value.confidence >= 0 &&
    value.confidence <= 1
  );
}

function isInspectionIssue(value: unknown): value is InspectionIssue {
  return (
    isRecord(value) &&
    typeof value.entityId === "string" &&
    Array.isArray(value.missing) &&
    value.missing.every(
      (field) => typeof field === "string" && evidenceFields.has(field)
    )
  );
}

function isPointBox(value: unknown): value is CadPointBox {
  return (
    isRecord(value) &&
    isPoint3(value.min) &&
    isPoint3(value.max)
  );
}

function isPoint3(value: unknown): value is [number, number, number] {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every((coordinate) =>
      typeof coordinate === "number" && Number.isFinite(coordinate)
    )
  );
}

const inspectionAgentIds = new Set<string>([
  "orchestrator",
  "drawing-index-agent",
  "search-agent",
  "rule-check-agent",
  "evidence-agent",
  "viewer-agent",
  "report-agent"
]);

const evidenceFields = new Set<string>([
  "id",
  "handle",
  "type",
  "layer",
  "bbox"
]);

function isInspectionCheck(value: unknown): value is InspectionCheck {
  if (!isRecord(value) || typeof value.kind !== "string") return false;
  if (
    typeof value.value !== "string" ||
    value.value.trim().length < 1 ||
    value.value.length > (
      value.kind === "text" ? MAX_CAD_SEARCH_QUERY_CHARS : 200
    )
  ) {
    return false;
  }
  if (value.kind === "text") {
    return (
      hasOnlyKeys(value, ["kind", "value", "regex"]) &&
      (value.regex === undefined || typeof value.regex === "boolean")
    );
  }
  return (
    (value.kind === "layer" || value.kind === "type") &&
    hasOnlyKeys(value, ["kind", "value"])
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]) {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}
