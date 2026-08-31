import type { CadEntityGeometry } from "@dwg/contracts";

import { arcPath } from "./geometryMath";

type ArcGeometryData = Extract<CadEntityGeometry, { kind: "arc" }>;

interface Props {
  geometry: ArcGeometryData;
  className: string;
  handle: string | null;
}

export function ArcGeometry({
  geometry,
  className,
  handle
}: Props) {
  const path = arcPath(geometry);
  if (!path) return null;
  return (
    <path
      className={className}
      data-handle={handle}
      data-geometry-kind="arc"
      d={path}
      fill="none"
    />
  );
}
