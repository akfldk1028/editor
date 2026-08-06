import {
  MAX_CAD_DRAWING_COMPARISON_ENTRIES,
  isCadDrawingComparison,
  isCadEntityIndex,
  type CadChangedField,
  type CadDrawingChange,
  type CadDrawingComparison,
  type CadEntityIndex,
  type CadEntityIndexItem,
  type CadEntityMatch,
  type CadPointBox
} from "@dwg/contracts";

const BBOX_TOLERANCE = 0.000001;
export const MAX_CAD_DRAWING_COMPARISON_INPUT_ENTITIES =
  MAX_CAD_DRAWING_COMPARISON_ENTRIES * 2;
export const MAX_CAD_DRAWING_COMPARISON_WORK_ITEMS =
  MAX_CAD_DRAWING_COMPARISON_ENTRIES * 2;

export interface CadDrawingComparisonOptions {
  signal?: AbortSignal;
}

interface EntityOccurrence {
  entity: CadEntityIndexItem;
  index: number;
}

interface OccurrenceQueue {
  items: EntityOccurrence[];
  cursor: number;
}

export function compareCadDrawings(
  before: CadEntityIndex,
  after: CadEntityIndex,
  options: CadDrawingComparisonOptions = {}
): CadDrawingComparison {
  requireNotAborted(options.signal);
  assertComparisonBudget(before, after);
  assertCadIndex(before);
  assertCadIndex(after);
  requireNotAborted(options.signal);

  const beforeOccurrences = before.entities.map(
    (entity, index): EntityOccurrence => ({ entity, index })
  );
  const afterOccurrences = after.entities.map(
    (entity, index): EntityOccurrence => ({ entity, index })
  );
  const beforeOrder = [...beforeOccurrences].sort(compareOccurrences);
  const afterOrder = [...afterOccurrences].sort(compareOccurrences);
  const matchedAfter = new Uint8Array(afterOccurrences.length);
  const matchedAfterByBefore: Array<EntityOccurrence | undefined> =
    new Array(beforeOccurrences.length);
  const afterByHandle = buildQueues(
    afterOrder,
    (occurrence) => occurrence.entity.handle
  );

  for (let position = 0; position < beforeOrder.length; position += 1) {
    checkpoint(options.signal, position);
    const beforeOccurrence = beforeOrder[position]!;
    if (beforeOccurrence.entity.handle === null) continue;
    const afterOccurrence = takeNext(
      afterByHandle.get(beforeOccurrence.entity.handle),
      matchedAfter
    );
    if (!afterOccurrence) continue;
    matchedAfter[afterOccurrence.index] = 1;
    matchedAfterByBefore[beforeOccurrence.index] = afterOccurrence;
  }

  const afterById = buildQueues(
    afterOrder,
    (occurrence) => occurrence.entity.id,
    matchedAfter
  );
  for (let position = 0; position < beforeOrder.length; position += 1) {
    checkpoint(options.signal, position);
    const beforeOccurrence = beforeOrder[position]!;
    if (matchedAfterByBefore[beforeOccurrence.index]) continue;
    const afterOccurrence = takeNext(
      afterById.get(beforeOccurrence.entity.id),
      matchedAfter
    );
    if (!afterOccurrence) continue;
    matchedAfter[afterOccurrence.index] = 1;
    matchedAfterByBefore[beforeOccurrence.index] = afterOccurrence;
  }

  const comparison: CadDrawingComparison = {
    added: [],
    removed: [],
    changed: []
  };
  let entryCount = 0;
  for (let position = 0; position < afterOrder.length; position += 1) {
    checkpoint(options.signal, position);
    const occurrence = afterOrder[position]!;
    if (matchedAfter[occurrence.index] === 1) continue;
    entryCount = reserveOutputEntry(entryCount);
    comparison.added.push(toMatch(occurrence.entity));
  }
  for (let position = 0; position < beforeOrder.length; position += 1) {
    checkpoint(options.signal, position);
    const occurrence = beforeOrder[position]!;
    const matched = matchedAfterByBefore[occurrence.index];
    if (!matched) {
      entryCount = reserveOutputEntry(entryCount);
      comparison.removed.push(toMatch(occurrence.entity));
      continue;
    }
    const change = toChange(occurrence.entity, matched.entity);
    if (change) {
      entryCount = reserveOutputEntry(entryCount);
      comparison.changed.push(change);
    }
  }
  requireNotAborted(options.signal);
  if (!isCadDrawingComparison(comparison)) {
    throw new Error("CAD drawing comparison output violates its public contract.");
  }
  return comparison;
}

function buildQueues(
  order: readonly EntityOccurrence[],
  keyOf: (occurrence: EntityOccurrence) => string | null,
  matched?: Uint8Array
): Map<string, OccurrenceQueue> {
  const queues = new Map<string, OccurrenceQueue>();
  for (const occurrence of order) {
    if (matched?.[occurrence.index] === 1) continue;
    const key = keyOf(occurrence);
    if (key === null) continue;
    const queue = queues.get(key);
    if (queue) {
      queue.items.push(occurrence);
    } else {
      queues.set(key, { items: [occurrence], cursor: 0 });
    }
  }
  return queues;
}

function takeNext(
  queue: OccurrenceQueue | undefined,
  matched: Uint8Array
): EntityOccurrence | undefined {
  if (!queue) return undefined;
  while (queue.cursor < queue.items.length) {
    const occurrence = queue.items[queue.cursor++]!;
    if (matched[occurrence.index] !== 1) return occurrence;
  }
  return undefined;
}

function reserveOutputEntry(current: number): number {
  if (current >= MAX_CAD_DRAWING_COMPARISON_ENTRIES) {
    throw new RangeError("CAD drawing comparison exceeds the maximum entry count.");
  }
  return current + 1;
}

function assertComparisonBudget(before: unknown, after: unknown): void {
  const beforeCount = entityCount(before);
  const afterCount = entityCount(after);
  if (
    beforeCount > MAX_CAD_DRAWING_COMPARISON_INPUT_ENTITIES ||
    afterCount > MAX_CAD_DRAWING_COMPARISON_INPUT_ENTITIES
  ) {
    throw new RangeError(
      `CAD drawing comparison input exceeds ${MAX_CAD_DRAWING_COMPARISON_INPUT_ENTITIES} entities per drawing.`
    );
  }
  if (beforeCount + afterCount > MAX_CAD_DRAWING_COMPARISON_WORK_ITEMS) {
    throw new RangeError(
      `CAD drawing comparison work budget exceeds ${MAX_CAD_DRAWING_COMPARISON_WORK_ITEMS} entity occurrences.`
    );
  }
}

function entityCount(value: unknown): number {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return 0;
  const entities = (value as Record<string, unknown>).entities;
  return Array.isArray(entities) ? entities.length : 0;
}

function toChange(
  before: CadEntityIndexItem,
  after: CadEntityIndexItem
): CadDrawingChange | null {
  const fields: CadChangedField[] = [];
  if (before.type !== after.type) fields.push("type");
  if (before.layer !== after.layer) fields.push("layer");
  if (!sameBox(before.bbox, after.bbox)) fields.push("bbox");
  if (before.text !== after.text) fields.push("text");
  return fields.length === 0
    ? null
    : { before: toMatch(before), after: toMatch(after), fields };
}

function toMatch(entity: CadEntityIndexItem): CadEntityMatch {
  return {
    id: entity.id,
    handle: entity.handle,
    type: entity.type,
    layer: entity.layer,
    bbox: entity.bbox === null ? null : normalizeBox(entity.bbox),
    text: entity.text,
    reason: "matched drawing evidence",
    confidence: entity.bbox === null ? 0.5 : 1
  };
}

function normalizeBox(box: CadPointBox): CadPointBox {
  return {
    min: [box.min[0], box.min[1], box.min[2]],
    max: [box.max[0], box.max[1], box.max[2]]
  };
}

function sameBox(left: CadPointBox | null, right: CadPointBox | null): boolean {
  if (left === null || right === null) return left === right;
  return left.min.every((coordinate, index) =>
    Math.abs(coordinate - right.min[index]!) <= BBOX_TOLERANCE
  ) && left.max.every((coordinate, index) =>
    Math.abs(coordinate - right.max[index]!) <= BBOX_TOLERANCE
  );
}

function compareOccurrences(left: EntityOccurrence, right: EntityOccurrence): number {
  return compareEntitiesByEvidence(left.entity, right.entity) ||
    left.index - right.index;
}

function compareEntitiesByEvidence(
  left: Pick<CadEntityIndexItem, "handle" | "id">,
  right: Pick<CadEntityIndexItem, "handle" | "id">
): number {
  return (left.handle ?? left.id).localeCompare(right.handle ?? right.id) ||
    left.id.localeCompare(right.id);
}

function assertCadIndex(value: unknown): asserts value is CadEntityIndex {
  if (!isCadEntityIndex(value)) {
    throw new TypeError("CAD drawing comparison requires valid CAD entity indexes.");
  }
}

function checkpoint(signal: AbortSignal | undefined, position: number): void {
  if ((position & 255) === 0) requireNotAborted(signal);
}

function requireNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new Error("CAD read operation was cancelled.");
  }
}
