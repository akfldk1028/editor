import type {
  CadEntityIndex,
  CadEntityIndexItemV02,
  CadEntityIndexV02
} from "@dwg/contracts";

export interface CadDocumentLayer {
  id: string;
  name: string;
  color: number | null;
  visible: boolean;
  frozen: boolean;
  locked: boolean | null;
}

export interface CadDocumentSnapshot {
  documentId: string;
  revision: number;
  sourceSha256: string;
  drawingVersion: string | null;
  units: string | null;
  index: CadEntityIndexV02;
  layers: CadDocumentLayer[];
}

export function normalizeEditableIndex(index: CadEntityIndex): CadEntityIndexV02 {
  validateEntityEvidence(index);

  if (index.schemaVersion === "cad-index/v0.2") {
    return {
      ...structuredClone(index),
      drawing: normalizeDrawingMetadata(index.drawing),
      layers: normalizeLayers(index.layers)
    };
  }

  return {
    ...structuredClone(index),
    schemaVersion: "cad-index/v0.2",
    drawing: normalizeDrawingMetadata(),
    layers: normalizeLayers(index.layers),
    entities: index.entities.map((entity) => ({
      ...structuredClone(entity),
      geometry: entity.bbox === null
        ? { kind: "unavailable", reason: "legacy-v0.1-no-bbox" }
        : { kind: "bbox", reason: "legacy-v0.1" }
    }))
  };
}

export function createDocumentSnapshot(
  index: CadEntityIndex,
  sourceSha256: string
): CadDocumentSnapshot {
  if (!/^[0-9a-f]{64}$/i.test(sourceSha256)) {
    throw new Error("sourceSha256 must be a SHA-256 hex digest.");
  }

  const editableIndex = normalizeEditableIndex(index);
  return {
    documentId: editableIndex.drawingId,
    revision: 0,
    sourceSha256: sourceSha256.toUpperCase(),
    drawingVersion: editableIndex.drawing?.fileVersion ?? null,
    units: editableIndex.drawing?.units ?? null,
    index: editableIndex,
    layers: editableIndex.layers.map((layer) => ({
      id: `layer:imported:${base64UrlUtf8(layer.name)}`,
      name: layer.name,
      color: layer.color ?? null,
      visible: layer.visible,
      frozen: layer.frozen,
      locked: layer.locked ?? null
    }))
  };
}

function normalizeDrawingMetadata(
  drawing?: CadEntityIndexV02["drawing"]
): NonNullable<CadEntityIndexV02["drawing"]> {
  return {
    fileVersion: drawing?.fileVersion ?? null,
    units: drawing?.units ?? null
  };
}

function normalizeLayers(
  layers: CadEntityIndex["layers"]
): CadEntityIndexV02["layers"] {
  return layers.map((layer) => ({
    ...layer,
    color: layer.color ?? null,
    locked: layer.locked ?? null
  }));
}

function validateEntityEvidence(index: CadEntityIndex): void {
  const handles = new Set<string>();
  for (const entity of index.entities) {
    if (entity.handle !== null) {
      if (handles.has(entity.handle)) {
        throw new Error(`Duplicate CAD handle: ${entity.handle}`);
      }
      handles.add(entity.handle);
    }
    assertFiniteGeometry(entity);
  }
}

function assertFiniteGeometry(entity: CadEntityIndex["entities"][number]): void {
  assertFiniteNumbers(entity.bbox);
  assertFiniteNumbers(entity.geometry);
}

function assertFiniteNumbers(value: unknown): void {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("CAD geometry must contain only finite numbers.");
    }
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) assertFiniteNumbers(item);
    return;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) assertFiniteNumbers(item);
  }
}

function base64UrlUtf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let output = "";

  for (let index = 0; index < bytes.length; index += 3) {
    const first = bytes[index];
    const second = bytes[index + 1];
    const third = bytes[index + 2];
    output += alphabet[first >> 2];
    output += alphabet[((first & 0x03) << 4) | ((second ?? 0) >> 4)];
    output += second === undefined ? "=" : alphabet[((second & 0x0f) << 2) | ((third ?? 0) >> 6)];
    output += third === undefined ? "=" : alphabet[third & 0x3f];
  }

  return output.replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}
