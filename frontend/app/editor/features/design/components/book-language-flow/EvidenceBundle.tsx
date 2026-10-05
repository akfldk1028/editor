import { useMemo, useState } from 'react';
import { ChevronDown } from 'lucide-react';

import type { ExplorationGraphEdge, ExplorationGraphNode } from '../../lib/language-system-types';

interface EvidenceBundleProps {
  node: ExplorationGraphNode | null;
  nodes: ExplorationGraphNode[];
  edges: ExplorationGraphEdge[];
}

function valueLabel(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(valueLabel).join(' · ');
  return JSON.stringify(value);
}

export function EvidenceBundle({ node, nodes, edges }: EvidenceBundleProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const nodesById = useMemo(() => new Map(nodes.map((item) => [item.id, item])), [nodes]);
  const evidence = (node?.evidence_ids ?? [])
    .map((id) => nodesById.get(id))
    .filter((item): item is ExplorationGraphNode => Boolean(item));
  const internalDetails = useMemo(() => {
    if (!node) return [];
    const result: ExplorationGraphNode[] = [];
    const visited = new Set([node.id]);
    let frontier = [node.id];
    for (let depth = 0; depth < 3; depth += 1) {
      const next: string[] = [];
      edges.forEach((edge) => {
        if (edge.scope !== 'detail' || !frontier.includes(edge.source) || visited.has(edge.target)) return;
        visited.add(edge.target);
        next.push(edge.target);
        const detail = nodesById.get(edge.target);
        if (detail) result.push(detail);
      });
      frontier = next;
    }
    return result;
  }, [edges, node, nodesById]);

  if (!node) {
    return (
      <aside className="book-evidence book-evidence--empty">
        <span>NODE INSPECTOR</span>
        <p>노드를 선택하면 BOOK 원본, 실행 속성, 내부 생성 상세를 한 묶음으로 확인합니다.</p>
      </aside>
    );
  }

  return (
    <aside className="book-evidence">
      <div className="book-evidence__heading">
        <div>
          <span>{node.authority.toUpperCase()} / {node.kind.replaceAll('_', ' ').toUpperCase()}</span>
          <h4>{node.label}</h4>
        </div>
        <code>{node.id}</code>
      </div>

      {evidence.length > 0 && (
        <div className="book-evidence__language-sources" aria-label="Language rule provenance">
          <span>LANGUAGE RULE PROVENANCE</span>
          <ul>
            {evidence.map((item) => (
              <li key={item.id}>
                <strong>{item.label}</strong>
                <span>{String(item.attributes.section ?? 'BOOK language source')}</span>
                <code>{item.id}</code>
              </li>
            ))}
          </ul>
          <p>BOOK raster scans are not visual evidence. Generated MASS renders appear only in ACTUAL EXECUTED MASS.</p>
        </div>
      )}

      <dl className="book-evidence__attributes">
        {Object.entries(node.attributes).slice(0, 9).map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll('_', ' ')}</dt>
            <dd>{valueLabel(value)}</dd>
          </div>
        ))}
      </dl>

      {internalDetails.length > 0 && (
        <div className="book-evidence__details">
          <button type="button" onClick={() => setDetailsOpen((current) => !current)} aria-expanded={detailsOpen}>
            <span>INTERNAL INSTANTIATION · {internalDetails.length}</span>
            <ChevronDown size={14} data-open={detailsOpen} />
          </button>
          {detailsOpen && (
            <ul>
              {internalDetails.map((detail) => (
                <li key={detail.id}><b>{detail.label}</b><span>{detail.kind.replaceAll('_', ' ')}</span></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}
