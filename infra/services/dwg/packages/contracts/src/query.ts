import type { CadEntityMatch, CadPointBox } from "./cad.js";

export const MAX_CAD_SCHEDULE_ROWS = 1_000;
export const MAX_CAD_SCHEDULE_CELLS_PER_ROW = 1_000;
export const MAX_CAD_DRAWING_COMPARISON_ENTRIES = 2_000;

export interface CadScheduleQuery {
  drawingId: string;
  matches: CadEntityMatch[];
  yTolerance: number;
}

export interface CadDrawingComparisonQuery {
  beforeDrawingId: string;
  afterDrawingId: string;
}

export interface CadScheduleRow {
  sourceHandles: string[];
  cells: string[];
  layer: string;
  bbox: CadPointBox | null;
}

export interface CadSchedule {
  rows: CadScheduleRow[];
}

export type CadChangedField = "type" | "layer" | "bbox" | "text";

export interface CadDrawingChange {
  before: CadEntityMatch;
  after: CadEntityMatch;
  fields: CadChangedField[];
}

export interface CadDrawingComparison {
  added: CadEntityMatch[];
  removed: CadEntityMatch[];
  changed: CadDrawingChange[];
}

export function parseCadScheduleQuery(value: unknown): CadScheduleQuery {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["drawingId", "matches", "yTolerance"])
  ) {
    throw new TypeError("Invalid CAD schedule query.");
  }
  if (
    !isIdentifier(value.drawingId) ||
    !Array.isArray(value.matches) ||
    value.matches.length > MAX_CAD_SCHEDULE_ROWS ||
    !value.matches.every(isCadEntityMatch) ||
    !isPositiveFinite(value.yTolerance)
  ) {
    throw new TypeError("Invalid CAD schedule query.");
  }
  return {
    drawingId: value.drawingId,
    matches: value.matches,
    yTolerance: value.yTolerance
  };
}

export function parseCadDrawingComparisonQuery(
  value: unknown
): CadDrawingComparisonQuery {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["afterDrawingId", "beforeDrawingId"]) ||
    !isIdentifier(value.beforeDrawingId) ||
    !isIdentifier(value.afterDrawingId)
  ) {
    throw new TypeError("Invalid CAD drawing comparison query.");
  }
  return {
    beforeDrawingId: value.beforeDrawingId,
    afterDrawingId: value.afterDrawingId
  };
}

export function isCadSchedule(value: unknown): value is CadSchedule {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["rows"]) &&
    Array.isArray(value.rows) &&
    value.rows.length <= MAX_CAD_SCHEDULE_ROWS &&
    value.rows.every(isCadScheduleRow)
  );
}

export function isCadDrawingComparison(value: unknown): value is CadDrawingComparison {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["added", "changed", "removed"]) &&
    Array.isArray(value.added) &&
    Array.isArray(value.removed) &&
    Array.isArray(value.changed) &&
    value.added.length + value.removed.length + value.changed.length <=
      MAX_CAD_DRAWING_COMPARISON_ENTRIES &&
    value.added.every(isCadEntityMatch) &&
    value.removed.every(isCadEntityMatch) &&
    value.changed.every(isCadDrawingChange)
  );
}

function isCadScheduleRow(value: unknown): value is CadScheduleRow {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["bbox", "cells", "layer", "sourceHandles"]) &&
    Array.isArray(value.sourceHandles) &&
    value.sourceHandles.length > 0 &&
    value.sourceHandles.length <= MAX_CAD_SCHEDULE_CELLS_PER_ROW &&
    value.sourceHandles.every(isIdentifier) &&
    Array.isArray(value.cells) &&
    value.cells.length === value.sourceHandles.length &&
    value.cells.length <= MAX_CAD_SCHEDULE_CELLS_PER_ROW &&
    value.cells.every(isBoundedString) &&
    isBoundedString(value.layer) &&
    (value.bbox === null || isCadPointBox(value.bbox))
  );
}

function isCadDrawingChange(value: unknown): value is CadDrawingChange {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["after", "before", "fields"]) &&
    isCadEntityMatch(value.before) &&
    isCadEntityMatch(value.after) &&
    Array.isArray(value.fields) &&
    value.fields.length > 0 &&
    hasExactChangedFields(value.fields)
  );
}

function hasExactChangedFields(value: unknown[]): value is CadChangedField[] {
  let previous = -1;
  for (const field of value) {
    if (typeof field !== "string") return false;
    const position = changedFieldOrder.indexOf(field as CadChangedField);
    if (position <= previous) return false;
    previous = position;
  }
  return true;
}

function isCadEntityMatch(value: unknown): value is CadEntityMatch {
  return (
    isRecord(value) &&
    hasAllowedKeys(value, ["bbox", "confidence", "handle", "id", "layer", "reason", "text", "type"]) &&
    isIdentifier(value.id) &&
    (value.handle === null || isIdentifier(value.handle)) &&
    isBoundedString(value.type) &&
    isBoundedString(value.layer) &&
    (value.bbox === null || isCadPointBox(value.bbox)) &&
    (value.text === undefined || value.text === null || isBoundedString(value.text)) &&
    isBoundedString(value.reason) &&
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    value.confidence >= 0 &&
    value.confidence <= 1
  );
}

function isCadPointBox(value: unknown): value is CadPointBox {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["max", "min"]) &&
    isPoint3(value.min) &&
    isPoint3(value.max)
  );
}

function isPoint3(value: unknown): value is [number, number, number] {
  return Array.isArray(value) && value.length === 3 && value.every(isFiniteNumber);
}

function isIdentifier(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 200;
}

function isBoundedString(value: unknown): value is string {
  return typeof value === "string" && value.length <= 8_192;
}

function isPositiveFinite(value: unknown): value is number {
  return isFiniteNumber(value) && value > 0 && value <= 1_000_000;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function hasAllowedKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

const changedFieldOrder: readonly CadChangedField[] = [
  "type",
  "layer",
  "bbox",
  "text"
];
