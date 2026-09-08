import type { CadEntityGeometry } from "@dwg/contracts";

import { polylinePath } from "./geometryMath";

type PolylineGeometryData = Extract<
  CadEntityGeometry,
  { kind: "lwpolyline" }
>;

interface Props {
  geometry: PolylineGeometryData;
  className: string;
  handle: string | null;
}

export function PolylineGeometry({
  geometry,
  className,
  handle
}: Props) {
  const path = polylinePath(geometry);
  if (!path) return null;
  return (
    <path
      className={className}
      data-handle={handle}
      data-geometry-kind="lwpolyline"
      d={path}
      fill="none"
    />
  );
}
