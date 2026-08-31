import { Crosshair, Focus, Grid3X3, Maximize2, Minimize2, MousePointer2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { CadEntity, CadIndex } from "../../shared/types";
import { EntityGeometry } from "./geometry/EntityGeometry";
import "./styles.css";

interface Props {
  index: CadIndex;
  highlightedHandles: ReadonlySet<string>;
  selectedHandle: string | null;
  searchQuery: string;
  gridVisible: boolean;
  hiddenLayers: ReadonlySet<string>;
  onGridVisibleChange(visible: boolean): void;
  showMaximize?: boolean;
}

const view = { minX: -24, minY: -12, width: 148, height: 126 };
const maximumSvgEntities = 2000;

export function CadViewer({
  index,
  highlightedHandles,
  selectedHandle,
  searchQuery,
  gridVisible,
  hiddenLayers,
  onGridVisibleChange,
  showMaximize = true
}: Props) {
  const [viewMode, setViewMode] = useState<"default" | "fit">("fit");
  const [maximized, setMaximized] = useState(false);
  const modelEntities = useMemo(
    () => index.entities.filter((entity) => entity.layout === "Model"),
    [index.entities]
  );
  const fitView = useMemo(
    () => calculateFitView(modelEntities),
    [modelEntities]
  );
  const visibleModelEntityCount = modelEntities.filter(
    (entity) => !hiddenLayers.has(entity.layer)
  ).length;
  const activeView = viewMode === "fit" ? fitView : view;
  const revision = index.schemaVersion === "cad-index/v0.2" ? index.drawing?.revision ?? 0 : 0;
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const highlightSet = new Set(highlightedHandles);
  if (selectedHandle) highlightSet.add(selectedHandle);

  if (normalizedQuery) {
    index.entities.forEach((entity) => {
      if (
        entity.handle?.toLowerCase().includes(normalizedQuery) ||
        entity.layer.toLowerCase().includes(normalizedQuery) ||
        entity.type.toLowerCase().includes(normalizedQuery)
      ) {
        if (entity.handle) highlightSet.add(entity.handle);
      }
    });
  }
  const renderedEntityCount = Math.min(
    visibleModelEntityCount,
    maximumSvgEntities
  );
  const yMirror = activeView.minY * 2 + activeView.height;

  useEffect(() => {
    if (!maximized) return;
    function exitMaximized(event: KeyboardEvent) {
      if (event.key === "Escape") setMaximized(false);
    }
    window.addEventListener("keydown", exitMaximized);
    return () => window.removeEventListener("keydown", exitMaximized);
  }, [maximized]);

  const renderedEntities = index.schemaVersion === "cad-index/v0.2"
    ? selectRenderableEntities(
        index.entities.filter((entity) =>
          entity.layout === "Model" && !hiddenLayers.has(entity.layer)
        ),
        highlightSet
      )
        .map((entity) => (
          <EntityGeometry
            entity={entity}
            highlighted={Boolean(
              entity.handle && highlightSet.has(entity.handle)
            )}
            key={entity.id}
            schemaVersion="cad-index/v0.2"
          />
        ))
    : selectRenderableEntities(
        index.entities.filter((entity) =>
          entity.layout === "Model" && !hiddenLayers.has(entity.layer)
        ),
        highlightSet
      )
        .map((entity) => (
          <EntityGeometry
            entity={entity}
            highlighted={Boolean(
              entity.handle && highlightSet.has(entity.handle)
            )}
            key={entity.id}
            schemaVersion="cad-index/v0.1"
          />
        ));

  return (
    <main className={`viewer-shell ${maximized ? "viewer-maximized" : ""}`} aria-label="CAD 뷰어">
      <div className="viewer-toolbar">
        <div className="tool-group">
          <button aria-label="선택" aria-pressed="true" className="tool-button active"><MousePointer2 size={14} /></button>
          <button
            aria-label="전체 보기"
            className={`tool-button ${viewMode === "fit" ? "active" : ""}`}
            onClick={() => setViewMode("fit")}
          >
            <Focus size={14} />
          </button>
          <button
            aria-label="그리드"
            aria-pressed={gridVisible}
            className="tool-button"
            onClick={() => onGridVisibleChange(!gridVisible)}
          >
            <Grid3X3 size={14} />
          </button>
        </div>
        <div className="viewer-crumb">Model <span>/</span> World UCS</div>
        {showMaximize && <button
          className={`tool-button ${maximized ? "active" : ""}`}
          aria-label={maximized ? "최대화 종료" : "최대화"}
          onClick={() => setMaximized((value) => !value)}
        >
          {maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>}
      </div>

      <div className="canvas-wrap" data-testid="cad-canvas" data-view={viewMode}>
        <svg
          className="cad-canvas"
          viewBox={`${activeView.minX} ${activeView.minY} ${activeView.width} ${activeView.height}`}
          role="img"
          aria-label={`${index.summary.modelSpaceCount}개 객체가 표시된 DWG 도면`}
        >
          <defs>
            <pattern id="minor-grid" width="5" height="5" patternUnits="userSpaceOnUse">
              <path d="M 5 0 L 0 0 0 5" className="minor-grid" />
            </pattern>
            <pattern id="major-grid" width="25" height="25" patternUnits="userSpaceOnUse">
              <rect width="25" height="25" fill="url(#minor-grid)" />
              <path d="M 25 0 L 0 0 0 25" className="major-grid" />
            </pattern>
          </defs>
          {gridVisible && (
            <rect
              className="cad-grid"
              x={activeView.minX}
              y={activeView.minY}
              width={activeView.width}
              height={activeView.height}
              fill="url(#major-grid)"
            />
          )}
          <g transform={`translate(0 ${yMirror}) scale(1 -1)`}>
            {renderedEntities}
          </g>
        </svg>

        <div className="axis-gizmo" aria-hidden="true">
          <span className="axis-y">Y</span><span className="axis-x">X</span>
          <Crosshair size={14} />
        </div>
        <div className="scale-readout">1:100&nbsp;&nbsp;|&nbsp;&nbsp;mm</div>
      </div>

      <div className="viewer-status">
        <span><i className="status-dot ready" /> Indexed</span>
        <span>
          {renderedEntityCount < visibleModelEntityCount
            ? `${renderedEntityCount} rendered / ${visibleModelEntityCount} visible`
            : `${visibleModelEntityCount} visible / ${modelEntities.length} total`}
        </span>
        <span>Model space</span>
        <span>Revision {revision}</span>
        <span className="coordinates">X 50.000&nbsp;&nbsp; Y 50.000&nbsp;&nbsp; Z 0.000</span>
      </div>
    </main>
  );
}

function selectRenderableEntities<T extends CadEntity>(
  entities: T[],
  highlightedHandles: ReadonlySet<string>
): T[] {
  if (entities.length <= maximumSvgEntities) return entities;
  const highlighted = entities.filter(
    (entity) => entity.handle && highlightedHandles.has(entity.handle)
  );
  const ordinary = entities.filter(
    (entity) => !entity.handle || !highlightedHandles.has(entity.handle)
  );
  const highlightedWithinBudget = highlighted.slice(0, maximumSvgEntities);
  return [
    ...ordinary.slice(0, maximumSvgEntities - highlightedWithinBudget.length),
    ...highlightedWithinBudget
  ];
}

function calculateFitView(entities: CadEntity[]) {
  const boxes = entities.flatMap((entity) => entity.bbox ? [entity.bbox] : []);
  if (boxes.length === 0) return view;
  const minX = Math.min(...boxes.map((box) => box.min[0]));
  const minY = Math.min(...boxes.map((box) => box.min[1]));
  const maxX = Math.max(...boxes.map((box) => box.max[0]));
  const maxY = Math.max(...boxes.map((box) => box.max[1]));
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  const padding = Math.max(width, height) * 0.08;
  return {
    minX: minX - padding,
    minY: minY - padding,
    width: width + padding * 2,
    height: height + padding * 2
  };
}
