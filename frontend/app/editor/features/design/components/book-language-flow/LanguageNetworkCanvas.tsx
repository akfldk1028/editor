import { requiredValue } from '../../lib/required-value';
import { useMemo } from 'react';

export interface NetworkNode {
  id: string;
  kind: string;
  stage: string;
  label: string;
  authority?: string;
  attributes: Record<string, unknown>;
}

export interface NetworkEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  scope?: string;
}

interface LanguageNetworkCanvasProps {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  stageOrder: string[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  axisLabels?: [string, string, string];
  stageLabels?: Record<string, string>;
  selectionPathNodeIds?: string[];
  selectionEdgeIds?: string[];
  includeDescendants?: boolean;
}

const CARD_WIDTH = 194;
const COLUMN_GAP = 66;
const ROW_HEIGHT = 30;
const CARD_TOP = 58;
const HEADER_HEIGHT = 62;
const STAGE_LABELS: Record<string, string> = {
  book_process_language: '00 · DESIGN PROCESS LANGUAGE',
  book_geometry_language: '02 · GEOMETRY / DIAGRAM LANGUAGE',
  base_model: '00 · BASE MODEL',
  derived_volume: '01 · DERIVED BOOK VOLUME',
  orientation: '02 · ORIENTATION',
  operation_family: '03 · OPERATION FAMILY',
  cardinality: '04 · CARDINALITY',
  operation: '05 · BOOK OPERATIVE',
  combination: '05 · COMBINATION',
  aggregation_method: '06 · AGGREGATION METHOD',
  aggregation_expression: '07 · AGGREGATION EXPRESSION',
  implementation_language: '08 · IMPLEMENTATION LANGUAGE',
  variation: '05 · VARIATION FIELD',
  book_extension: '06 · COMBINATION / AGGREGATION',
  program: '07 · PROGRAM PROJECTION',
  capacity: '08 · CAPACITY ALT',
  hard_gate: '09 · HARD GATE',
  render: '10 · MASS PNG',
  vlm: '11 · VLM CRITIC',
  portfolio_memory: '12 · ACCEPTED MEMORY',
  seed: '00 · PROGRAM SEED',
  outcome_base_model: '01 · BOOK BASE MODEL',
  core_operator: '01 · CORE SOLID OPERATOR',
  architectural_macro: '02 · ARCHITECTURAL MACRO',
  phenotype: '03 · 18 MASS PHENOTYPES',
  compiler: '04 · GEOMETRY COMPILER',
  render_vlm_gate: '05 · RENDER / VLM / GATE',
  genotype: '01 · GEOMETRY GENOTYPE',
  compiled: '02 · COMPILED MASS',
  outcome: '03 · CANDIDATE OUTCOME',
  artifact: '04 · EVIDENCE ARTIFACT',
  critic: '05 · VLM VERDICT',
  portfolio: '06 · PORTFOLIO MEMORY',
  reference_corpus: 'REFERENCE CORPUS',
  reference_query: 'RETRIEVAL QUERY',
  execution_reference: 'RETRIEVED IMAGE · NOT YET LEARNED',
  execution_vlm_reference: 'VLM REFERENCE IMAGE · USED',
  reference_distill: 'VLM FEATURE DISTILLATION',
  execution_geometry: 'EXECUTED GEOMETRY PROGRAM',
  execution_program: 'USE / PROGRAM PROJECTION',
  execution_compiler: 'GEOMETRY COMPILER',
  execution_gates: 'SITE · LAW · PARKING GATES',
  execution_render: 'ACTUAL MASS RENDER',
  execution_vlm: 'VLM CRITIC · ACTUAL INPUTS ONLY',
  execution_repair: 'TYPED GEOMETRY REPAIR',
  execution_selector: 'FINAL SELECTOR',
  executed_mass: 'EXECUTED MASS RESULT',
  elevation_handoff: 'ELEVATION MESH HANDOFF',
  elevation_condition: 'ELEVATION CONDITION PACK',
  elevation_result: '6-VIEW GEOMETRY VERIFICATION',
  elevation_image_agent: 'ARCHITECTURAL RENDER AGENT',
  elevation_proposal: 'RENDER ALT 01',
  execution_elevation_handoff: 'ELEVATION MESH HANDOFF',
  execution_elevation_condition: 'ELEVATION CONDITION PACK',
  execution_elevation_result: '6-VIEW GEOMETRY VERIFICATION',
  execution_elevation_image_agent: 'ARCHITECTURAL RENDER AGENT',
  execution_elevation_proposal: 'RENDER ALT 01',
};

function rowHeight(node: NetworkNode) {
  if (typeof node.attributes.preview_url === 'string' && node.attributes.preview_url) return 126;
  return Array.isArray(node.attributes.matrix4) ? 84 : ROW_HEIGHT;
}

function BaseModelGlyph({ cells }: { cells: unknown }) {
  const safeCells = Array.isArray(cells) ? cells : [];
  return (
    <svg className="book-network__base-glyph" viewBox="0 0 26 26" aria-hidden="true">
      <rect x="2.5" y="2.5" width="21" height="21" />
      {safeCells.map((cell, index) => {
        const candidate = cell as { minimum?: number[]; maximum?: number[] };
        const minimum = candidate.minimum ?? [0, 0, 0];
        const maximum = candidate.maximum ?? [1, 1, 1];
        return (
          <rect
            key={`${minimum.join('-')}-${maximum.join('-')}-${index}`}
            x={2.5 + requiredValue(minimum[0]) * 21}
            y={2.5 + (1 - requiredValue(maximum[1])) * 21}
            width={Math.max(1, (requiredValue(maximum[0]) - requiredValue(minimum[0])) * 21)}
            height={Math.max(1, (requiredValue(maximum[1]) - requiredValue(minimum[1])) * 21)}
            data-cell="true"
          />
        );
      })}
    </svg>
  );
}

function Matrix4Glyph({ matrix }: { matrix: unknown }) {
  if (!Array.isArray(matrix) || matrix.length !== 4) return null;
  const values = matrix.flatMap((row) => (Array.isArray(row) ? row.slice(0, 4) : []));
  if (values.length !== 16) return null;
  return (
    <span className="book-network__matrix4" aria-label="homogeneous 4 by 4 transform matrix">
      {values.map((value, index) => (
        <code key={`${index}-${String(value)}`} title={String(value)}>
          {Number(value).toFixed(Number(value) % 1 === 0 ? 0 : 2)}
        </code>
      ))}
    </span>
  );
}

export function LanguageNetworkCanvas({
  nodes,
  edges,
  stageOrder,
  selectedNodeId,
  onSelectNode,
  axisLabels = ['BOOK AUTHORITY', 'EXECUTABLE EXPLORATION', 'EVIDENCE LOOP'],
  stageLabels,
  selectionPathNodeIds,
  selectionEdgeIds,
  includeDescendants = false,
}: LanguageNetworkCanvasProps) {
  const layout = useMemo(() => {
    const stages = stageOrder
      .map((stage) => ({ stage, nodes: nodes.filter((node) => node.stage === stage) }))
      .filter((entry) => entry.nodes.length > 0);
    const positions = new Map<string, { x: number; y: number }>();
    stages.forEach((entry, column) => {
      let offsetY = 0;
      entry.nodes.forEach((node) => {
        const height = rowHeight(node);
        positions.set(node.id, {
          x: 30 + column * (CARD_WIDTH + COLUMN_GAP),
          y: CARD_TOP + HEADER_HEIGHT + offsetY + height / 2,
        });
        offsetY += height;
      });
    });
    const maximumColumnHeight = Math.max(
      ROW_HEIGHT,
      ...stages.map((entry) => entry.nodes.reduce((total, node) => total + rowHeight(node), 0)),
    );
    return {
      stages,
      positions,
      width: Math.max(900, 60 + stages.length * (CARD_WIDTH + COLUMN_GAP)),
      height: Math.max(560, CARD_TOP + HEADER_HEIGHT + maximumColumnHeight + 42),
    };
  }, [nodes, stageOrder]);

  const focus = useMemo(() => {
    const nodeIds = new Set<string>();
    const edgeIds = new Set<string>();
    if (!selectedNodeId) return { nodeIds, edgeIds };

    if (selectionEdgeIds && selectionEdgeIds.length > 0) {
      const selectedEdges = new Set(selectionEdgeIds);
      edges.forEach((edge) => {
        if (!selectedEdges.has(edge.id)) return;
        edgeIds.add(edge.id);
        nodeIds.add(edge.source);
        nodeIds.add(edge.target);
      });
      nodeIds.add(selectedNodeId);
      return { nodeIds, edgeIds };
    }

    const addShortestPath = (sourceId: string, targetId: string) => {
      if (sourceId === targetId) {
        nodeIds.add(sourceId);
        return;
      }
      const queue = [sourceId];
      const visited = new Set([sourceId]);
      const previous = new Map<string, NetworkEdge>();
      while (queue.length > 0 && !visited.has(targetId)) {
        const current = queue.shift()!;
        edges.forEach((edge) => {
          if (edge.scope === 'pending' || edge.source !== current || visited.has(edge.target)) return;
          visited.add(edge.target);
          previous.set(edge.target, edge);
          queue.push(edge.target);
        });
      }
      if (!visited.has(targetId)) return;
      let cursor = targetId;
      nodeIds.add(cursor);
      while (cursor !== sourceId) {
        const edge = previous.get(cursor);
        if (!edge) break;
        edgeIds.add(edge.id);
        nodeIds.add(edge.source);
        cursor = edge.source;
      }
    };

    const anchors = (selectionPathNodeIds ?? []).filter((id) => nodes.some((node) => node.id === id));
    if (anchors.length > 0) {
      anchors.forEach((id) => nodeIds.add(id));
      for (let index = 1; index < anchors.length; index += 1) {
        addShortestPath(requiredValue(anchors[index - 1]), requiredValue(anchors[index]));
      }
      return { nodeIds, edgeIds };
    }

    nodeIds.add(selectedNodeId);
    const collect = (direction: 'ancestors' | 'descendants') => {
      const frontier = [selectedNodeId];
      const visited = new Set(frontier);
      while (frontier.length > 0) {
        const current = frontier.shift()!;
        edges.forEach((edge) => {
          if (edge.scope === 'pending') return;
          const matches = direction === 'ancestors' ? edge.target === current : edge.source === current;
          if (!matches) return;
          edgeIds.add(edge.id);
          const nextId = direction === 'ancestors' ? edge.source : edge.target;
          nodeIds.add(nextId);
          if (!visited.has(nextId)) {
            visited.add(nextId);
            frontier.push(nextId);
          }
        });
      }
    };
    collect('ancestors');
    if (includeDescendants) collect('descendants');
    return { nodeIds, edgeIds };
  }, [edges, includeDescendants, nodes, selectedNodeId, selectionEdgeIds, selectionPathNodeIds]);

  const drawableEdges = edges.filter(
    (edge) => layout.positions.has(edge.source) && layout.positions.has(edge.target),
  );
  const renderedEdges = selectedNodeId
    ? drawableEdges.filter((edge) => focus.edgeIds.has(edge.id))
    : drawableEdges;

  return (
    <div className="book-network" style={{ width: layout.width, height: layout.height }}>
      <div className="book-network__axis" aria-hidden="true">
        <span>{axisLabels[0]}</span><i /><span>{axisLabels[1]}</span><i /><span>{axisLabels[2]}</span>
      </div>
      <svg
        className="book-network__edges"
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        aria-hidden="true"
      >
        <defs>
          <filter id="book-edge-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {renderedEdges.map((edge) => {
          const source = layout.positions.get(edge.source)!;
          const target = layout.positions.get(edge.target)!;
          const x1 = source.x + CARD_WIDTH;
          const x2 = target.x;
          const bend = Math.max(30, Math.abs(x2 - x1) * 0.46);
          return (
            <path
              key={edge.id}
              d={`M ${x1} ${source.y} C ${x1 + bend} ${source.y}, ${x2 - bend} ${target.y}, ${x2} ${target.y}`}
              className={`book-network__edge${edge.scope === 'pending' ? ' is-pending' : ' is-active'}${edge.scope === 'feedback' ? ' is-feedback' : ''}`}
              data-edge-id={edge.id}
              data-edge-source={edge.source}
              data-edge-target={edge.target}
              data-edge-relation={edge.kind}
              data-edge-scope={edge.scope ?? 'observed'}
            />
          );
        })}
      </svg>

      {layout.stages.map((entry, column) => (
        <section
          className="book-network__stage"
          key={entry.stage}
          data-stage={entry.stage}
          style={{
            left: 30 + column * (CARD_WIDTH + COLUMN_GAP),
            top: CARD_TOP,
            width: CARD_WIDTH,
            height: HEADER_HEIGHT + entry.nodes.reduce((total, node) => total + rowHeight(node), 0),
          }}
        >
          <header>
            <span>{stageLabels?.[entry.stage] ?? STAGE_LABELS[entry.stage] ?? entry.stage.replaceAll('_', ' ').toUpperCase()}</span>
            <strong>{entry.nodes.length.toString().padStart(2, '0')}</strong>
          </header>
          <div>
            {entry.nodes.map((node, row) => {
              const selected = node.id === selectedNodeId;
              const related = focus.nodeIds.has(node.id);
              return (
                <button
                  type="button"
                  key={node.id}
                  className="book-network__node"
                  data-node-id={node.id}
                  data-node-kind={node.kind}
                  data-node-stage={node.stage}
                  data-selected={selected}
                  data-related={related}
                  data-authority={node.authority ?? 'observed'}
                  data-has-preview={typeof node.attributes.preview_url === 'string' && Boolean(node.attributes.preview_url)}
                  data-has-matrix={Array.isArray(node.attributes.matrix4)}
                  onClick={() => onSelectNode(node.id)}
                  title={`${node.label}\n${node.kind}`}
                >
                  <span>{(row + 1).toString().padStart(2, '0')}</span>
                  {(node.kind === 'base_model' || node.kind === 'derived_volume') && <BaseModelGlyph cells={node.attributes.cells} />}
                  <Matrix4Glyph matrix={node.attributes.matrix4} />
                  {typeof node.attributes.preview_url === 'string' && node.attributes.preview_url && (
                    <img src={node.attributes.preview_url} alt={`${node.label} four-view MASS result`} />
                  )}
                  <b>{node.label}</b>
                  <i aria-hidden="true" />
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
