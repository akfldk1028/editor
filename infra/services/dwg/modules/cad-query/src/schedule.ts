import {
  MAX_CAD_SCHEDULE_CELLS_PER_ROW,
  MAX_CAD_SCHEDULE_ROWS,
  isCadEntityIndex,
  isCadSchedule,
  type CadEntityIndex,
  type CadEntityIndexItem,
  type CadPointBox,
  type CadSchedule
} from "@dwg/contracts";

export interface CadScheduleExtractionOptions {
  sourceHandles?: readonly string[];
  yTolerance?: number;
}

const DEFAULT_Y_TOLERANCE = 1;

interface PositionedText {
  entity: CadEntityIndexItem & {
    handle: string;
    text: string;
    bbox: CadPointBox;
  };
  x: number;
  y: number;
}

interface ScheduleBand {
  anchorY: number;
  layer: string;
  cells: PositionedText[];
}

export function extractCadSchedule(
  index: CadEntityIndex,
  options: CadScheduleExtractionOptions = {}
): CadSchedule {
  assertCadIndex(index);
  const yTolerance = options.yTolerance ?? DEFAULT_Y_TOLERANCE;
  if (!Number.isFinite(yTolerance) || yTolerance <= 0 || yTolerance > 1_000_000) {
    throw new TypeError("CAD schedule Y tolerance must be a positive finite number.");
  }

  const sourceHandles = options.sourceHandles === undefined
    ? null
    : new Set(options.sourceHandles);
  const positioned: PositionedText[] = index.entities.flatMap((entity) => {
    if (
      sourceHandles !== null &&
      (entity.handle === null || !sourceHandles.has(entity.handle))
    ) {
      return [];
    }
    if (!isPositionedText(entity)) return [];
    return [{ entity, x: entity.bbox.min[0], y: entity.bbox.min[1] }];
  }).sort(compareForBands);
  const bands: ScheduleBand[] = [];

  for (const candidate of positioned) {
    const last = bands[bands.length - 1];
    if (!last || last.layer !== candidate.entity.layer || Math.abs(last.anchorY - candidate.y) > yTolerance) {
      if (bands.length >= MAX_CAD_SCHEDULE_ROWS) {
        throw new RangeError("CAD schedule exceeds the maximum row count.");
      }
      bands.push({ anchorY: candidate.y, layer: candidate.entity.layer, cells: [candidate] });
      continue;
    }
    if (last.cells.length >= MAX_CAD_SCHEDULE_CELLS_PER_ROW) {
      throw new RangeError("CAD schedule row exceeds the maximum cell count.");
    }
    last.cells.push(candidate);
  }

  const rows: CadSchedule["rows"] = bands.sort(compareBands).map((band) => {
    const cells = [...band.cells].sort(compareCellsByX);
    return {
      sourceHandles: cells.map((cell) => cell.entity.handle!),
      cells: cells.map((cell) => cell.entity.text!),
      layer: band.layer,
      bbox: cells.slice(1).reduce(
        (bbox, cell) => unionBoxes(bbox, cell.entity.bbox!),
        normalizeBox(cells[0]!.entity.bbox!)
      )
    };
  });
  const schedule = { rows };
  if (!isCadSchedule(schedule)) {
    throw new Error("CAD schedule output violates its public contract.");
  }
  return schedule;
}

function normalizeBox(box: CadPointBox): CadPointBox {
  return {
    min: [box.min[0], box.min[1], box.min[2]],
    max: [box.max[0], box.max[1], box.max[2]]
  };
}

function isPositionedText(entity: CadEntityIndexItem): entity is CadEntityIndexItem & {
  handle: string;
  text: string;
  bbox: CadPointBox;
} {
  return (
    (entity.type === "TEXT" || entity.type === "MTEXT") &&
    entity.handle !== null &&
    entity.text !== null &&
    entity.bbox !== null
  );
}

function compareForBands(left: PositionedText, right: PositionedText): number {
  return (
    left.entity.layer.localeCompare(right.entity.layer) ||
    right.y - left.y ||
    left.x - right.x ||
    left.entity.handle.localeCompare(right.entity.handle) ||
    left.entity.id.localeCompare(right.entity.id)
  );
}

function compareBands(left: ScheduleBand, right: ScheduleBand): number {
  return right.anchorY - left.anchorY || left.layer.localeCompare(right.layer);
}

function compareCellsByX(left: PositionedText, right: PositionedText): number {
  return (
    left.x - right.x ||
    left.entity.handle.localeCompare(right.entity.handle) ||
    left.entity.id.localeCompare(right.entity.id)
  );
}

function unionBoxes(left: CadPointBox, right: CadPointBox): CadPointBox {
  return {
    min: [
      Math.min(left.min[0], right.min[0]),
      Math.min(left.min[1], right.min[1]),
      Math.min(left.min[2], right.min[2])
    ],
    max: [
      Math.max(left.max[0], right.max[0]),
      Math.max(left.max[1], right.max[1]),
      Math.max(left.max[2], right.max[2])
    ]
  };
}

function assertCadIndex(value: unknown): asserts value is CadEntityIndex {
  if (!isCadEntityIndex(value)) {
    throw new TypeError("CAD schedule requires a valid CAD entity index.");
  }
}
