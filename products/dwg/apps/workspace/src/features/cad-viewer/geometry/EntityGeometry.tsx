import type {
  CadEntityIndexItemV01,
  CadEntityIndexItemV02
} from "@dwg/contracts";

import { ArcGeometry } from "./ArcGeometry";
import { BboxFallback } from "./BboxFallback";
import { PolylineGeometry } from "./PolylineGeometry";
import { TextGeometry } from "./TextGeometry";

type Props =
  | {
      schemaVersion: "cad-index/v0.1";
      entity: CadEntityIndexItemV01;
      highlighted: boolean;
    }
  | {
      schemaVersion: "cad-index/v0.2";
      entity: CadEntityIndexItemV02;
      highlighted: boolean;
    };

export function EntityGeometry(props: Props) {
  const className =
    `cad-entity ${props.highlighted ? "highlighted" : ""}`;
  if (props.schemaVersion === "cad-index/v0.1") {
    return (
      <BboxFallback
        entity={props.entity}
        className={className}
        kind="legacy"
      />
    );
  }
  return renderV02(props.entity, className);
}

function renderV02(
  entity: CadEntityIndexItemV02,
  className: string
) {
  switch (entity.geometry.kind) {
    case "line":
      return (
        <line
          className={className}
          data-handle={entity.handle}
          data-geometry-kind="line"
          x1={entity.geometry.start[0]}
          y1={entity.geometry.start[1]}
          x2={entity.geometry.end[0]}
          y2={entity.geometry.end[1]}
        />
      );
    case "circle":
      return (
        <circle
          className={className}
          data-handle={entity.handle}
          data-geometry-kind="circle"
          cx={entity.geometry.center[0]}
          cy={entity.geometry.center[1]}
          r={entity.geometry.radius}
        />
      );
    case "arc":
      return (
        <ArcGeometry
          geometry={entity.geometry}
          className={className}
          handle={entity.handle}
        />
      );
    case "lwpolyline":
      return (
        <PolylineGeometry
          geometry={entity.geometry}
          className={className}
          handle={entity.handle}
        />
      );
    case "point":
      return (
        <circle
          className={className}
          data-handle={entity.handle}
          data-geometry-kind="point"
          cx={entity.geometry.position[0]}
          cy={entity.geometry.position[1]}
          r="1.8"
        />
      );
    case "text":
      return (
        <TextGeometry
          geometry={entity.geometry}
          text={entity.text ?? ""}
          className={className}
          handle={entity.handle}
        />
      );
    case "insert":
      return (
        <BboxFallback
          entity={entity}
          className={className}
          kind="insert"
        />
      );
    case "bbox":
      return (
        <BboxFallback
          entity={entity}
          className={className}
          kind="bbox"
        />
      );
    case "unavailable":
      return (
        <BboxFallback
          entity={entity}
          className={className}
          kind="unavailable"
        />
      );
  }
}
