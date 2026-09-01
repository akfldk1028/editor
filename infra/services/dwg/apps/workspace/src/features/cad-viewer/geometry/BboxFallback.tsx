import type {
  CadEntityIndexItemV01,
  CadEntityIndexItemV02
} from "@dwg/contracts";

interface Props {
  entity: CadEntityIndexItemV01 | CadEntityIndexItemV02;
  className: string;
  kind: "legacy" | "insert" | "bbox" | "unavailable";
}

export function BboxFallback({ entity, className, kind }: Props) {
  if (!entity.bbox) return null;
  const [x1, y1] = entity.bbox.min;
  const [x2, y2] = entity.bbox.max;
  const width = Math.max(x2 - x1, 0.7);
  const height = Math.max(y2 - y1, 0.7);
  const geometryKind = kind === "insert" ? "insert" : "bbox";
  return (
    <g
      className={`${className} geometry-fallback`}
      data-handle={entity.handle}
      data-geometry-kind={geometryKind}
    >
      <rect
        x={x1}
        y={y1}
        width={width}
        height={height}
        fill="none"
      />
      {kind === "insert" && (
        <>
          <line x1={x1 - 0.8} y1={y1} x2={x1 + 0.8} y2={y1} />
          <line x1={x1} y1={y1 - 0.8} x2={x1} y2={y1 + 0.8} />
        </>
      )}
    </g>
  );
}
