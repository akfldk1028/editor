import React from 'react';
import { useViewport, type Edge, type Node } from '@xyflow/react';
import type { AGLightEdgeData } from './types';

interface Props {
  nodes: Node[];
  edges: Edge<AGLightEdgeData>[];
}

const getNodeBox = (node: Node) => ({
  x: node.position.x,
  y: node.position.y,
  width: Number(node.width || node.initialWidth || 128),
  height: Number(node.height || node.initialHeight || 86),
});

const getPathGeometry = (
  source: ReturnType<typeof getNodeBox>,
  target: ReturnType<typeof getNodeBox>,
  routingType?: AGLightEdgeData['routingType']
) => {
  const sourceCenterX = source.x + source.width / 2;
  const sourceCenterY = source.y + source.height / 2;
  const targetCenterX = target.x + target.width / 2;
  const targetCenterY = target.y + target.height / 2;

  if (routingType === 'feedback') {
    const sourceX = source.x;
    const targetX = target.x + target.width;
    const controlY = Math.min(source.y, target.y) - 180;
    return {
      d: `M ${sourceX} ${sourceCenterY} C ${sourceX - 180} ${controlY}, ${targetX + 180} ${controlY}, ${targetX} ${targetCenterY}`,
      labelX: (sourceX + targetX) / 2,
      labelY: controlY + 8,
    };
  }

  const horizontal = Math.abs(targetCenterX - sourceCenterX) >= Math.abs(targetCenterY - sourceCenterY);
  if (horizontal) {
    const movesRight = targetCenterX >= sourceCenterX;
    const sourceX = movesRight ? source.x + source.width : source.x;
    const targetX = movesRight ? target.x : target.x + target.width;
    const delta = Math.max(72, Math.abs(targetX - sourceX) * 0.48);
    const direction = movesRight ? 1 : -1;
    return {
      d: `M ${sourceX} ${sourceCenterY} C ${sourceX + delta * direction} ${sourceCenterY}, ${targetX - delta * direction} ${targetCenterY}, ${targetX} ${targetCenterY}`,
      labelX: (sourceX + targetX) / 2,
      labelY: (sourceCenterY + targetCenterY) / 2 - 10,
    };
  }

  const movesDown = targetCenterY >= sourceCenterY;
  const sourceY = movesDown ? source.y + source.height : source.y;
  const targetY = movesDown ? target.y : target.y + target.height;
  const delta = Math.max(72, Math.abs(targetY - sourceY) * 0.48);
  const direction = movesDown ? 1 : -1;
  return {
    d: `M ${sourceCenterX} ${sourceY} C ${sourceCenterX} ${sourceY + delta * direction}, ${targetCenterX} ${targetY - delta * direction}, ${targetCenterX} ${targetY}`,
    labelX: (sourceCenterX + targetCenterX) / 2,
    labelY: (sourceY + targetY) / 2 - 10,
  };
};

export default function EdgeOverlay({ nodes, edges }: Props) {
  const viewport = useViewport();
  const nodeMap = React.useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  return (
    <svg
      aria-hidden="true"
      data-testid="ag-light-edge-overlay"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 1,
        overflow: 'visible',
      }}
    >
      <defs>
        <filter id="ag-light-edge-glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="4" result="blur" />
        </filter>
      </defs>
      <g transform={`translate(${viewport.x}, ${viewport.y}) scale(${viewport.zoom})`}>
        {edges.map((edge) => {
          const sourceNode = nodeMap.get(edge.source);
          const targetNode = nodeMap.get(edge.target);
          if (!sourceNode || !targetNode) return null;
          const routingType = edge.data?.routingType;
          const stroke = routingType === 'secondary'
            ? '#0891b2'
            : String(edge.style?.stroke || '#38bdf8');
          const strokeWidth = Number(edge.style?.strokeWidth || 1.5);
          const opacity = Number(edge.style?.opacity ?? 1);
          const geometry = getPathGeometry(getNodeBox(sourceNode), getNodeBox(targetNode), routingType);
          const label = String(edge.data?.label || '');
          const labelWidth = Math.max(0, label.length * 6.2 + 18);

          return (
            <g key={edge.id}>
              <path
                d={geometry.d}
                fill="none"
                stroke={stroke}
                strokeWidth={strokeWidth * 4.2}
                opacity={Math.max(opacity * 0.14, 0.06)}
                filter="url(#ag-light-edge-glow)"
                strokeLinecap="round"
              />
              <path
                data-testid="ag-light-edge-path"
                d={geometry.d}
                fill="none"
                stroke={stroke}
                strokeWidth={strokeWidth}
                strokeDasharray={edge.style?.strokeDasharray as string | undefined}
                opacity={Math.max(opacity, 0.34)}
                strokeLinecap="round"
              />
              {label && (
                <g transform={`translate(${geometry.labelX}, ${geometry.labelY})`}>
                  <rect
                    x={-labelWidth / 2}
                    y={-10}
                    width={labelWidth}
                    height={20}
                    rx={10}
                    fill="rgba(2,6,23,0.9)"
                    stroke={stroke}
                    strokeOpacity={0.32}
                  />
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill="#cbd5e1"
                    fontSize="10"
                    fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
                  >
                    {label}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
