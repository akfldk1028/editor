import { useMemo, useState } from 'react';

import type { MassActivationNode, MassExecutionPassport } from '../../lib/language-system-types';

interface MassExecutionGraphProps {
  passport: MassExecutionPassport;
  compact?: boolean;
  resultImageUrl?: string;
}

const COLUMN_ORDER = [
  'base', 'book', 'geometry', 'program', 'compiler', 'gate', 'site',
  'capacity', 'law', 'parking', 'program_fit', 'render', 'reference', 'vlm', 'repair', 'selector', 'result',
  'elevation_handoff', 'elevation_condition', 'elevation_result', 'elevation_image_agent', 'elevation_proposal',
];

function visibleImageUrl(node: MassActivationNode, resultImageUrl?: string) {
  if (node.kind === 'mass_result' || node.kind === 'mass_render_result') return resultImageUrl ?? '';
  const imageUrl = String(node.evidence.preview_url ?? node.evidence.image_url ?? '');
  return imageUrl.startsWith('/') || imageUrl.startsWith('https://') || imageUrl.startsWith('http://') || imageUrl.startsWith('data:')
    ? imageUrl
    : '';
}

function statusLabel(status: string) {
  if (status === 'not_evaluated') return 'NOT EVALUATED';
  return status.replaceAll('_', ' ').toUpperCase();
}

function compactEvidence(value: Record<string, unknown>) {
  const entries = Object.entries(value).filter(([, item]) => item !== '' && item !== null && item !== undefined);
  return entries.slice(0, 12).map(([key, item]) => (
    <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof item === 'object' ? JSON.stringify(item) : String(item)}</dd></div>
  ));
}

export function MassExecutionGraph({ passport, compact = false, resultImageUrl }: MassExecutionGraphProps) {
  const [selectedId, setSelectedId] = useState('flow:selector');
  const graph = passport.activation_graph;
  const layout = useMemo(() => {
    const present = new Set(graph.nodes.map((node) => node.column));
    const columns = [
      ...COLUMN_ORDER.filter((column) => present.has(column)),
      ...[...present].filter((column) => !COLUMN_ORDER.includes(column)).sort(),
    ];
    const grouped = new Map<string, MassActivationNode[]>();
    columns.forEach((column) => grouped.set(column, []));
    graph.nodes.forEach((node) => grouped.get(node.column)?.push(node));
    const xStep = compact ? 126 : 164;
    const yStep = compact ? 30 : 38;
    const width = Math.max(760, columns.length * xStep + 100);
    const height = Math.max(
      compact ? 280 : 430,
      ...columns.map((column) => (grouped.get(column)?.length ?? 0) * yStep + 100),
    );
    const positions = new Map<string, { x: number; y: number }>();
    columns.forEach((column, columnIndex) => {
      const items = grouped.get(column) ?? [];
      const contentHeight = Math.max(0, (items.length - 1) * yStep);
      const startY = 68 + Math.max(0, (height - 110 - contentHeight) / 2);
      items.forEach((node, rowIndex) => positions.set(node.id, {
        x: 52 + columnIndex * xStep,
        y: startY + rowIndex * yStep,
      }));
    });
    return { columns, grouped, positions, width, height, xStep };
  }, [compact, graph.nodes]);
  const selected = graph.nodes.find((node) => node.id === selectedId) ?? graph.nodes[0];

  return (
    <section className={`mass-execution${compact ? ' mass-execution--compact' : ''}`} data-testid="mass-execution-graph">
      <header className="mass-execution__header">
        <div><span>PER-MASS CAUSAL PASSPORT</span><strong>{passport.mass_id.slice(0, 28)}</strong></div>
        <div className="mass-execution__legend"><i />REAL PASS <i className="pending" />NOT EVALUATED</div>
      </header>
      <div className="mass-execution__scroll">
        <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="선택한 MASS의 실제 실행 활성 경로">
          <g className="mass-execution__columns">
            {layout.columns.map((column, index) => (
              <g key={column}>
                <line x1={52 + index * layout.xStep} y1="42" x2={52 + index * layout.xStep} y2={layout.height - 24} />
                <text x={52 + index * layout.xStep} y="24">{column.replaceAll('_', ' ').toUpperCase()}</text>
              </g>
            ))}
          </g>
          <g className="mass-execution__edges">
            {graph.edges.map((edge) => {
              const source = layout.positions.get(edge.source);
              const target = layout.positions.get(edge.target);
              if (!source || !target) return null;
              const dx = Math.max(24, (target.x - source.x) * 0.46);
              const active = edge.activation > 0;
              const selectedEdge = edge.source === selectedId || edge.target === selectedId;
              return <path
                key={edge.id}
                d={`M ${source.x} ${source.y} C ${source.x + dx} ${source.y}, ${target.x - dx} ${target.y}, ${target.x} ${target.y}`}
                className={`${active ? 'is-active' : 'is-pending'}${selectedEdge ? ' is-selected' : ''}`}
                style={{ strokeWidth: active ? 0.55 + edge.activation * 1.25 : 0.45 }}
              />;
            })}
          </g>
          <g className="mass-execution__nodes">
            {graph.nodes.map((node) => {
              const position = layout.positions.get(node.id);
              if (!position) return null;
              const active = node.activation > 0;
              const selectedNode = node.id === selected?.id;
              const imageUrl = visibleImageUrl(node, resultImageUrl);
              return (
                <g
                  key={node.id}
                  data-node-id={node.id}
                  data-node-kind={node.kind}
                  transform={`translate(${position.x} ${position.y})`}
                  className={`${active ? 'is-active' : 'is-pending'}${selectedNode ? ' is-selected' : ''}`}
                  onClick={() => setSelectedId(node.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      setSelectedId(node.id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  {imageUrl ? (
                    <>
                      <rect className="mass-execution__image-frame" x="-15" y="-13" width="30" height="26" rx="1" />
                      <image href={imageUrl} x="-13" y="-11" width="26" height="22" preserveAspectRatio="xMidYMid slice" />
                    </>
                  ) : (
                    <circle r={selectedNode ? 6.2 : 4.2 + Math.max(0, node.activation) * 1.2} />
                  )}
                  <text x={imageUrl ? 20 : 10} y="3.5">{node.label.slice(0, compact ? 14 : 20)}</text>
                  <title>{node.label} · {statusLabel(node.status)}</title>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      {selected && !compact && (
        <div className="mass-execution__inspection">
          <div><span>SELECTED ACTIVITY</span><strong>{selected.label}</strong><code>{selected.id}</code></div>
          <dl>
            <div><dt>STATUS</dt><dd>{statusLabel(selected.status)}</dd></div>
            <div><dt>ACTIVATION</dt><dd>{selected.activation.toFixed(3)} · recorded evidence only</dd></div>
            {compactEvidence(selected.evidence)}
          </dl>
        </div>
      )}
    </section>
  );
}
