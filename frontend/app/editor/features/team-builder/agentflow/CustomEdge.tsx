/**
 * CustomEdge - Custom React Flow edge with bidirectional routing
 * Ported from AutoGen Studio edge.tsx
 */

import { EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react'
import { memo } from 'react'
import type { CustomEdgeData } from './types'

/** Horizontal offset for secondary/self-loop edge routing */
const EDGE_OFFSET = 140

interface CustomEdgeProps extends Omit<EdgeProps, 'data'> {
  data: CustomEdgeData
}

export const CustomEdge = memo(function CustomEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  source,
  target,
  data,
  style = {},
  markerEnd,
}: CustomEdgeProps) {
  const isSelfLoop = source === target
  const baseStrokeWidth = (style.strokeWidth as number) || 1
  const messageCount = data?.messages?.length ?? 0
  const finalStrokeWidth = isSelfLoop
    ? Math.max(baseStrokeWidth, 2)
    : Math.min(Math.max(messageCount, 1), 5) * baseStrokeWidth

  let edgePath = ''
  let labelX = 0
  let labelY = 0

  if (data?.routingType === 'secondary' || isSelfLoop) {
    const midY = (sourceY + targetY) / 2
    edgePath = `
      M ${sourceX},${sourceY}
      L ${sourceX},${sourceY + 10}
      L ${sourceX + EDGE_OFFSET},${sourceY + 10}
      L ${sourceX + EDGE_OFFSET},${targetY - 10}
      L ${targetX},${targetY - 10}
      L ${targetX},${targetY}
    `
    labelX = sourceX + EDGE_OFFSET
    labelY = midY
  } else {
    ;[edgePath, labelX, labelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
    })
  }

  // Label position offset for bidirectional edges
  const getLabelPosition = (x: number, y: number) => {
    if (!data?.routingType || isSelfLoop) return { x, y }
    const verticalOffset = data.routingType === 'secondary' ? -20 : 20
    return { x, y: y + verticalOffset }
  }

  const labelPosition = getLabelPosition(labelX, labelY)

  return (
    <>
      <path
        id={id}
        className="react-flow__edge-path"
        d={edgePath}
        style={{
          ...style,
          strokeWidth: finalStrokeWidth,
          stroke: data?.routingType === 'secondary' ? '#0891b2' : (style.stroke as string),
        }}
        markerEnd={markerEnd}
      />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelPosition.x}px,${labelPosition.y}px)`,
              pointerEvents: 'all',
            }}
            onClick={data.onClick}
          >
            <div
              className="px-2 py-0.5 rounded text-xs bg-(--color-background-secondary) text-(--color-text-primary) border border-(--color-border-default) cursor-pointer hover:scale-110 transition-transform flex items-center gap-1"
              style={{ whiteSpace: 'nowrap' }}
            >
              {messageCount > 0 && (
                <span className="text-(--color-text-tertiary)">({messageCount})</span>
              )}
              <span>{data.label}</span>
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
})
