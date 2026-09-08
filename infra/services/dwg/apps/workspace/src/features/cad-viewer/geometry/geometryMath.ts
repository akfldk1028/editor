import type {
  CadEntityGeometry,
  CadPoint3
} from "@dwg/contracts";

type ArcGeometryData = Extract<CadEntityGeometry, { kind: "arc" }>;
type PolylineGeometryData = Extract<
  CadEntityGeometry,
  { kind: "lwpolyline" }
>;

export interface SvgArcSegment {
  radius: number;
  largeArc: 0 | 1;
  sweep: 0 | 1;
}

const tau = Math.PI * 2;
const tolerance = 1e-9;

export function arcPath(geometry: ArcGeometryData): string | null {
  if (
    !isPoint3(geometry.center) ||
    !isPositiveFinite(geometry.radius) ||
    !Number.isFinite(geometry.startAngle) ||
    !Number.isFinite(geometry.endAngle) ||
    !isPlanarNormal(geometry.normal)
  ) {
    return null;
  }

  const delta = normalizeSweep(
    geometry.endAngle - geometry.startAngle
  );
  if (delta <= tolerance) {
    return null;
  }

  const startX =
    geometry.center[0] + geometry.radius * Math.cos(geometry.startAngle);
  const startY =
    geometry.center[1] + geometry.radius * Math.sin(geometry.startAngle);
  const endX =
    geometry.center[0] + geometry.radius * Math.cos(geometry.endAngle);
  const endY =
    geometry.center[1] + geometry.radius * Math.sin(geometry.endAngle);
  const largeArc = delta > Math.PI ? 1 : 0;
  const sweep = geometry.normal[2] > 0 ? 1 : 0;

  return [
    "M",
    number(startX),
    number(startY),
    "A",
    number(geometry.radius),
    number(geometry.radius),
    "0",
    largeArc,
    sweep,
    number(endX),
    number(endY)
  ].join(" ");
}

export function bulgeSegment(
  start: CadPoint3,
  end: CadPoint3,
  bulge: number
): SvgArcSegment | null {
  if (
    !isPoint3(start) ||
    !isPoint3(end) ||
    !Number.isFinite(bulge) ||
    Math.abs(bulge) <= tolerance
  ) {
    return null;
  }

  const chord = Math.hypot(
    end[0] - start[0],
    end[1] - start[1]
  );
  const includedAngle = 4 * Math.atan(Math.abs(bulge));
  const denominator = 2 * Math.sin(includedAngle / 2);
  if (chord <= tolerance || Math.abs(denominator) <= tolerance) {
    return null;
  }

  const radius = chord / denominator;
  if (!isPositiveFinite(radius)) {
    return null;
  }
  return {
    radius,
    largeArc: includedAngle > Math.PI ? 1 : 0,
    sweep: bulge > 0 ? 1 : 0
  };
}

export function polylinePath(
  geometry: PolylineGeometryData
): string | null {
  if (
    geometry.vertices.length === 0 ||
    !isPlanarNormal(geometry.normal) ||
    !geometry.vertices.every((vertex) =>
      isPoint3(vertex.point) &&
      Number.isFinite(vertex.bulge) &&
      Number.isFinite(vertex.startWidth) &&
      Number.isFinite(vertex.endWidth)
    )
  ) {
    return null;
  }

  const commands = [
    "M",
    number(geometry.vertices[0].point[0]),
    number(geometry.vertices[0].point[1])
  ];
  const segmentCount = geometry.closed
    ? geometry.vertices.length
    : geometry.vertices.length - 1;

  for (let index = 0; index < segmentCount; index += 1) {
    const start = geometry.vertices[index];
    const end = geometry.vertices[
      (index + 1) % geometry.vertices.length
    ];
    const arc = bulgeSegment(start.point, end.point, start.bulge);
    if (!arc) {
      commands.push("L", number(end.point[0]), number(end.point[1]));
      continue;
    }
    commands.push(
      "A",
      number(arc.radius),
      number(arc.radius),
      "0",
      String(arc.largeArc),
      String(arc.sweep),
      number(end.point[0]),
      number(end.point[1])
    );
  }

  if (geometry.closed) {
    commands.push("Z");
  }
  return commands.join(" ");
}

export function isPlanarNormal(normal: CadPoint3): boolean {
  return (
    isPoint3(normal) &&
    Math.abs(normal[0]) <= tolerance &&
    Math.abs(normal[1]) <= tolerance &&
    Math.abs(Math.abs(normal[2]) - 1) <= tolerance
  );
}

function normalizeSweep(angle: number): number {
  return ((angle % tau) + tau) % tau;
}

function isPoint3(value: CadPoint3): boolean {
  return (
    value.length === 3 &&
    value.every((coordinate) => Number.isFinite(coordinate))
  );
}

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function number(value: number): string {
  const rounded = Math.round(value * 1e12) / 1e12;
  return String(Object.is(rounded, -0) ? 0 : rounded);
}
