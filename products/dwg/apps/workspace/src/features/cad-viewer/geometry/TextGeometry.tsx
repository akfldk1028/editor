import type { CadEntityGeometry } from "@dwg/contracts";

type TextGeometryData = Extract<CadEntityGeometry, { kind: "text" }>;

interface Props {
  geometry: TextGeometryData;
  text: string;
  className: string;
  handle: string | null;
}

export function TextGeometry({
  geometry,
  text,
  className,
  handle
}: Props) {
  const [x, y] = geometry.insertionPoint;
  const rotation = geometry.rotation * 180 / Math.PI;
  const lines = text.split(/\r?\n/);
  return (
    <text
      className={`${className} cad-text`}
      data-handle={handle}
      data-geometry-kind="text"
      fontSize={geometry.height}
      transform={`translate(${x} ${y}) rotate(${-rotation}) scale(1 -1)`}
    >
      {lines.map((line, index) => (
        <tspan
          key={`${index}:${line}`}
          x="0"
          dy={index === 0 ? 0 : geometry.height * 1.2}
        >
          {line}
        </tspan>
      ))}
    </text>
  );
}
