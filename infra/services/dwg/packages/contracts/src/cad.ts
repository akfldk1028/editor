export type CadSourceKind = "dxf" | "dwg";
export type CadSpace = "model" | "paper" | "unknown";
export type CadPoint3 = [number, number, number];

export interface CadPointBox {
  min: CadPoint3;
  max: CadPoint3;
}

export interface CadIndexSource {
  kind: CadSourceKind;
  displayName: string;
  parser: string;
}

export interface CadIndexSummary {
  entityCount: number;
  layerCount: number;
  unsupportedCount: number;
  modelSpaceCount: number;
  paperSpaceCount: number;
}

export interface CadDrawingMetadata {
  fileVersion: string | null;
  units: string | null;
  /** In-memory edit revision; omitted by read-only parser results. */
  revision?: number;
}

export interface CadLayerIndexItem {
  name: string;
  entityCount: number;
  visible: boolean;
  frozen: boolean;
  color?: number | null;
  locked?: boolean | null;
}

export interface CadLwPolylineVertex {
  point: CadPoint3;
  bulge: number;
  startWidth: number;
  endWidth: number;
}

export type CadEntityGeometry =
  | {
      kind: "line";
      start: CadPoint3;
      end: CadPoint3;
    }
  | {
      kind: "circle";
      center: CadPoint3;
      radius: number;
      normal: CadPoint3;
    }
  | {
      kind: "arc";
      center: CadPoint3;
      radius: number;
      startAngle: number;
      endAngle: number;
      normal: CadPoint3;
    }
  | {
      kind: "lwpolyline";
      vertices: CadLwPolylineVertex[];
      closed: boolean;
      elevation: number;
      normal: CadPoint3;
    }
  | {
      kind: "point";
      position: CadPoint3;
    }
  | {
      kind: "text";
      insertionPoint: CadPoint3;
      alignmentPoint: CadPoint3 | null;
      height: number;
      rotation: number;
      width: number | null;
    }
  | {
      kind: "insert";
      insertionPoint: CadPoint3;
      rotation: number;
      scale: CadPoint3;
      normal: CadPoint3;
    }
  | {
      kind: "bbox";
      reason: string;
    }
  | {
      kind: "unavailable";
      reason: string;
    };

interface CadEntityIndexItemBase {
  id: string;
  handle: string | null;
  type: string;
  layer: string;
  space: CadSpace;
  layout: string;
  bbox: CadPointBox | null;
  text: string | null;
  blockName: string | null;
  attributes: Record<string, string>;
  warnings: string[];
}

export interface CadEntityIndexItemV01 extends CadEntityIndexItemBase {
  geometry: Record<string, unknown>;
}

export interface CadEntityIndexItemV02 extends CadEntityIndexItemBase {
  geometry: CadEntityGeometry;
}

export type CadEntityIndexItem =
  | CadEntityIndexItemV01
  | CadEntityIndexItemV02;

export interface CadEntityMatch {
  id: string;
  handle: string | null;
  type: string;
  layer: string;
  bbox: CadPointBox | null;
  text?: string | null;
  reason: string;
  confidence: number;
}

export interface UnsupportedCadEntity {
  type: string;
  count: number;
  reason: string;
}

interface CadEntityIndexBase {
  drawingId: string;
  source: CadIndexSource;
  summary: CadIndexSummary;
  layers: CadLayerIndexItem[];
  unsupported: UnsupportedCadEntity[];
}

export interface CadEntityIndexV01 extends CadEntityIndexBase {
  schemaVersion: "cad-index/v0.1";
  entities: CadEntityIndexItemV01[];
}

export interface CadEntityIndexV02 extends CadEntityIndexBase {
  schemaVersion: "cad-index/v0.2";
  drawing?: CadDrawingMetadata;
  entities: CadEntityIndexItemV02[];
}

export type CadEntityIndex = CadEntityIndexV01 | CadEntityIndexV02;

export function isCadEntityIndex(value: unknown): value is CadEntityIndex {
  return isCadEntityIndexV01(value) || isCadEntityIndexV02(value);
}

export function isCadEntityIndexV02(
  value: unknown
): value is CadEntityIndexV02 {
  return (
    isCadIndexEnvelope(value) &&
    value.schemaVersion === "cad-index/v0.2" &&
    value.entities.every(isCadEntityIndexItemV02)
  );
}

function isCadEntityIndexV01(value: unknown): value is CadEntityIndexV01 {
  return (
    isCadIndexEnvelope(value) &&
    value.schemaVersion === "cad-index/v0.1" &&
    value.entities.every(isCadEntityIndexItemV01)
  );
}

function isCadIndexEnvelope(
  value: unknown
): value is Record<string, unknown> & {
  schemaVersion: unknown;
  entities: unknown[];
} {
  if (!isRecord(value) || !Array.isArray(value.entities)) {
    return false;
  }
  return (
    typeof value.drawingId === "string" &&
    value.drawingId.length > 0 &&
    isCadIndexSource(value.source) &&
    isCadIndexSummary(value.summary) &&
    (value.drawing === undefined || isCadDrawingMetadata(value.drawing)) &&
    Array.isArray(value.layers) &&
    value.layers.every(isCadLayerIndexItem) &&
    Array.isArray(value.unsupported) &&
    value.unsupported.every(isUnsupportedCadEntity)
  );
}

function isCadDrawingMetadata(value: unknown): value is CadDrawingMetadata {
  return (
    isRecord(value) &&
    Object.keys(value).every((key) => key === "fileVersion" || key === "units" || key === "revision") &&
    (typeof value.fileVersion === "string" || value.fileVersion === null) &&
    (typeof value.units === "string" || value.units === null) &&
    (value.revision === undefined || isCount(value.revision))
  );
}

function isCadIndexSource(value: unknown): value is CadIndexSource {
  return (
    isRecord(value) &&
    (value.kind === "dxf" || value.kind === "dwg") &&
    typeof value.displayName === "string" &&
    typeof value.parser === "string"
  );
}

function isCadIndexSummary(value: unknown): value is CadIndexSummary {
  return (
    isRecord(value) &&
    isCount(value.entityCount) &&
    isCount(value.layerCount) &&
    isCount(value.unsupportedCount) &&
    isCount(value.modelSpaceCount) &&
    isCount(value.paperSpaceCount)
  );
}

function isCadLayerIndexItem(value: unknown): value is CadLayerIndexItem {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    isCount(value.entityCount) &&
    typeof value.visible === "boolean" &&
    typeof value.frozen === "boolean" &&
    (value.color === undefined || value.color === null || isFiniteNumber(value.color)) &&
    (value.locked === undefined || value.locked === null || typeof value.locked === "boolean")
  );
}

function isUnsupportedCadEntity(
  value: unknown
): value is UnsupportedCadEntity {
  return (
    isRecord(value) &&
    typeof value.type === "string" &&
    isCount(value.count) &&
    typeof value.reason === "string"
  );
}

function isCadEntityIndexItemV01(
  value: unknown
): value is CadEntityIndexItemV01 {
  return isCadEntityBase(value) && isRecord(value.geometry);
}

function isCadEntityIndexItemV02(
  value: unknown
): value is CadEntityIndexItemV02 {
  return isCadEntityBase(value) && isCadEntityGeometry(value.geometry);
}

function isCadEntityBase(
  value: unknown
): value is Record<string, unknown> & CadEntityIndexItemBase {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    (typeof value.handle === "string" || value.handle === null) &&
    typeof value.type === "string" &&
    typeof value.layer === "string" &&
    (value.space === "model" ||
      value.space === "paper" ||
      value.space === "unknown") &&
    typeof value.layout === "string" &&
    (value.bbox === null || isCadPointBox(value.bbox)) &&
    (typeof value.text === "string" || value.text === null) &&
    (typeof value.blockName === "string" || value.blockName === null) &&
    isStringRecord(value.attributes) &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === "string")
  );
}

function isCadEntityGeometry(value: unknown): value is CadEntityGeometry {
  if (!isRecord(value) || typeof value.kind !== "string") {
    return false;
  }
  switch (value.kind) {
    case "line":
      return (
        hasExactKeys(value, ["end", "kind", "start"]) &&
        isPoint3(value.start) &&
        isPoint3(value.end)
      );
    case "circle":
      return (
        hasExactKeys(value, ["center", "kind", "normal", "radius"]) &&
        isPoint3(value.center) &&
        isPositiveFinite(value.radius) &&
        isPoint3(value.normal)
      );
    case "arc":
      return (
        hasExactKeys(value, [
          "center",
          "endAngle",
          "kind",
          "normal",
          "radius",
          "startAngle"
        ]) &&
        isPoint3(value.center) &&
        isPositiveFinite(value.radius) &&
        isFiniteNumber(value.startAngle) &&
        isFiniteNumber(value.endAngle) &&
        isPoint3(value.normal)
      );
    case "lwpolyline":
      return (
        hasExactKeys(value, [
          "closed",
          "elevation",
          "kind",
          "normal",
          "vertices"
        ]) &&
        Array.isArray(value.vertices) &&
        value.vertices.every(isCadLwPolylineVertex) &&
        typeof value.closed === "boolean" &&
        isFiniteNumber(value.elevation) &&
        isPoint3(value.normal)
      );
    case "point":
      return (
        hasExactKeys(value, ["kind", "position"]) &&
        isPoint3(value.position)
      );
    case "text":
      return (
        hasExactKeys(value, [
          "alignmentPoint",
          "height",
          "insertionPoint",
          "kind",
          "rotation",
          "width"
        ]) &&
        isPoint3(value.insertionPoint) &&
        (value.alignmentPoint === null || isPoint3(value.alignmentPoint)) &&
        isPositiveFinite(value.height) &&
        isFiniteNumber(value.rotation) &&
        (value.width === null || isFiniteNumber(value.width))
      );
    case "insert":
      return (
        hasExactKeys(value, [
          "insertionPoint",
          "kind",
          "normal",
          "rotation",
          "scale"
        ]) &&
        isPoint3(value.insertionPoint) &&
        isFiniteNumber(value.rotation) &&
        isPoint3(value.scale) &&
        isPoint3(value.normal)
      );
    case "bbox":
    case "unavailable":
      return (
        hasExactKeys(value, ["kind", "reason"]) &&
        typeof value.reason === "string" &&
        value.reason.length > 0
      );
    default:
      return false;
  }
}

function isCadLwPolylineVertex(
  value: unknown
): value is CadLwPolylineVertex {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["bulge", "endWidth", "point", "startWidth"]) &&
    isPoint3(value.point) &&
    isFiniteNumber(value.bulge) &&
    isFiniteNumber(value.startWidth) &&
    isFiniteNumber(value.endWidth)
  );
}

function isCadPointBox(value: unknown): value is CadPointBox {
  return (
    isRecord(value) &&
    isPoint3(value.min) &&
    isPoint3(value.max)
  );
}

function isPoint3(value: unknown): value is CadPoint3 {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(isFiniteNumber)
  );
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    isRecord(value) &&
    Object.values(value).every((item) => typeof item === "string")
  );
}

function isCount(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isPositiveFinite(value: unknown): value is number {
  return isFiniteNumber(value) && value > 0;
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: string[]
): boolean {
  const actual = Object.keys(value).sort();
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type PointBox = CadPointBox;
export type CadEntity = CadEntityIndexItem;
export type CadIndex = CadEntityIndex;
