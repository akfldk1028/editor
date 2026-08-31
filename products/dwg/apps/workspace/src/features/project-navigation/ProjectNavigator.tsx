import {
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  FileBox,
  Layers3,
  LayoutTemplate
} from "lucide-react";
import { useMemo, useState } from "react";

import type { CadIndex } from "../../shared/types";
import "./styles.css";

interface Props {
  index: CadIndex;
  hiddenLayers: ReadonlySet<string>;
  query: string;
  onToggleLayer(layerName: string): void;
}

export function ProjectNavigator({ index, hiddenLayers, query, onToggleLayer }: Props) {
  const [layoutsOpen, setLayoutsOpen] = useState(true);
  const [layersOpen, setLayersOpen] = useState(true);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const layouts = useMemo(() => [...new Set(index.entities.map((entity) => entity.layout))], [index.entities]);
  const layers = index.layers.filter((layer) => layer.name.toLocaleLowerCase().includes(normalizedQuery));
  const revision = index.schemaVersion === "cad-index/v0.2" ? index.drawing?.revision ?? 0 : 0;

  return (
    <section aria-label="Project" className="project-navigation" role="region">
      <div className="project-navigation-scroll">
        <div aria-label="Drawing hierarchy" className="project-tree" role="tree">
          <div aria-expanded="true" aria-level={1} className="project-tree-root" role="treeitem">
            <FileBox aria-hidden="true" size={15} />
            <span className="project-name" title={index.source.displayName}>{index.source.displayName}</span>
          </div>
          <button
            aria-expanded={layoutsOpen}
            aria-level={2}
            className="project-tree-heading"
            onClick={() => setLayoutsOpen((open) => !open)}
            role="treeitem"
          >
            {layoutsOpen ? <ChevronDown aria-hidden="true" size={14} /> : <ChevronRight aria-hidden="true" size={14} />}
            <LayoutTemplate aria-hidden="true" size={14} />
            <span>Layouts</span><span className="project-tree-count">{layouts.length}</span>
          </button>
          {layoutsOpen && layouts.map((layout) => (
            <div aria-level={3} className="project-layout-row layout-row" key={layout} role="treeitem" title={layout}>
              <LayoutTemplate aria-hidden="true" size={13} /><span>{layout}</span>
            </div>
          ))}

          <button
            aria-expanded={layersOpen}
            aria-level={2}
            className="project-tree-heading"
            onClick={() => setLayersOpen((open) => !open)}
            role="treeitem"
          >
            {layersOpen ? <ChevronDown aria-hidden="true" size={14} /> : <ChevronRight aria-hidden="true" size={14} />}
            <Layers3 aria-hidden="true" size={14} />
            <span>Layers</span><span className="project-tree-count">{index.layers.length}</span>
          </button>
          {layersOpen && <div className="project-layer-header" role="presentation"><span /><span>Eye</span><span>Lock</span><span>Color</span><span>Count</span></div>}
          {layersOpen && layers.map((layer) => {
            const sourceAvailable = layer.visible && !layer.frozen;
            const effectiveVisible = sourceAvailable && !hiddenLayers.has(layer.name);
            const visibilityLabel = layer.frozen
              ? `Layer ${layer.name} is frozen`
              : !layer.visible
                ? `Layer ${layer.name} is hidden in source`
                : `${effectiveVisible ? "Hide" : "Show"} layer ${layer.name}`;
            return (
              <div aria-level={3} className="project-layer-row layer-row" key={layer.name} role="treeitem">
                <span className="project-layer-controls">
                  <button
                    aria-label={visibilityLabel}
                    aria-pressed={!effectiveVisible}
                    className="layer-visibility-button"
                    disabled={!sourceAvailable}
                    onClick={() => onToggleLayer(layer.name)}
                    type="button"
                  >
                    {effectiveVisible ? <Eye size={13} /> : <EyeOff size={13} />}
                  </button>
                  <span className="project-layer-lock">{layer.locked == null ? "Unknown" : layer.locked ? "Locked" : "Unlocked"}</span>
                  <LayerColor color={layer.color} />
                  <span aria-label={`${layer.entityCount} objects`} className="project-layer-count">{layer.entityCount}</span>
                </span>
                <span className="project-layer-name" title={layer.name}>{layer.name}</span>
              </div>
            );
          })}
          {layersOpen && layers.length === 0 && <div className="project-navigation-empty">No matching layers.</div>}
        </div>
      </div>
      <footer className="project-navigation-footer"><span>{index.summary.entityCount} objects</span><span>Revision {revision}</span><span>{index.schemaVersion}</span></footer>
    </section>
  );
}

function LayerColor({ color }: { color: number | null | undefined }) {
  if (color == null) return <span className="project-layer-color">Unknown</span>;
  return <span className="project-layer-color" title={`AutoCAD Color Index ${color}`}>
    <i className="project-layer-swatch" style={{ backgroundColor: aciColor(color) }} />
    ACI {color}
  </span>;
}

function aciColor(color: number) {
  const basic = ["#000000", "#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#000000", "#808080", "#c0c0c0"];
  if (Number.isInteger(color) && color >= 0 && color < basic.length) return basic[color]!;
  if (Number.isInteger(color) && color >= 10 && color <= 249) {
    const hue = Math.floor((color - 10) / 10) * 15;
    const shade = (color - 10) % 10;
    const saturation = shade % 2 === 0 ? 100 : 50;
    const lightness = [50, 75, 32, 48, 25, 37, 15, 22, 7, 11][shade]!;
    return `hsl(${hue} ${saturation}% ${lightness}%)`;
  }
  const grays = ["#333333", "#505050", "#696969", "#828282", "#bebebe", "#ffffff"];
  if (Number.isInteger(color) && color >= 250 && color <= 255) return grays[color - 250]!;
  return "#808080";
}
