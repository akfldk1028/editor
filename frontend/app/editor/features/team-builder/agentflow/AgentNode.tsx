/**
 * AgentNode - Custom React Flow node for agents
 * Ported from AutoGen Studio agentnode.tsx
 */

import { Handle, Position } from '@xyflow/react'
import { AlertTriangle, Bot, CheckCircle, Flag, StopCircle, UserCircle } from 'lucide-react'
import { memo } from 'react'
import type { AgentNodeData } from './types'

interface AgentNodeProps {
  data: AgentNodeData
  isConnectable: boolean
}

function AgentNode({ data, isConnectable }: AgentNodeProps) {
  const getHeaderIcon = () => {
    switch (data.type) {
      case 'user':
        return <UserCircle className="w-5 h-5 text-(--color-accent-primary)" />
      case 'agent':
        return <Bot className="w-5 h-5 text-(--color-accent-primary)" />
      case 'end':
        return <Flag className="w-5 h-5 text-(--color-accent-primary)" />
    }
  }

  const getStatusIcon = () => {
    if (data.type !== 'end' || !data.status) return null
    switch (data.status) {
      case 'complete':
        return <CheckCircle className="w-6 h-6 text-green-500" />
      case 'error':
        return <AlertTriangle className="w-6 h-6 text-red-500" />
      case 'stopped':
        return <StopCircle className="w-6 h-6 text-red-500" />
      default:
        return null
    }
  }

  const isActive = data.isActive
  const isEnd = data.type === 'end'
  const borderColor = isEnd
    ? data.status === 'complete'
      ? 'border-green-500'
      : data.status === 'error' || data.status === 'stopped'
        ? 'border-red-500'
        : 'border-(--color-border-default)'
    : 'border-(--color-border-default)'

  return (
    <div
      role="group"
      aria-label={`${data.type} node: ${data.label}`}
      data-testid={`agent-node-${data.label}`}
      className={`min-w-[170px] rounded-lg shadow-md overflow-hidden border ${borderColor} ${
        isActive ? 'ring-2 ring-(--color-accent-primary)/50' : ''
      } ${data.isHub ? 'ring-1 ring-offset-1' : ''}`}
      style={data.color && data.isHub ? { borderColor: data.color } : undefined}
    >
      {/* Target handle (input) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-(--color-text-tertiary) !w-2 !h-2"
        isConnectable={isConnectable}
        id="target"
      />

      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-(--color-background-secondary) border-b border-(--color-border-default)">
        {getHeaderIcon()}
        <span className="text-sm font-medium text-(--color-text-primary) truncate">
          {data.label}
        </span>
      </div>

      {/* Content */}
      <div className="bg-(--color-background-primary) px-3 py-2">
        {isEnd ? (
          <>
            <div className="flex items-center justify-center gap-2">
              {getStatusIcon()}
              <span className="text-sm font-medium text-(--color-text-primary)">
                {data.status && typeof data.status === 'string'
                  ? data.status.charAt(0).toUpperCase() + data.status.slice(1)
                  : ''}
              </span>
            </div>
            {data.reason && (
              <div className="mt-1 text-xs text-(--color-text-tertiary) max-w-[200px] text-center">
                {data.reason.length > 100 ? `${data.reason.substring(0, 97)}...` : data.reason}
              </div>
            )}
          </>
        ) : (
          <>
            {data.lastMessage ? (
              <div
                className="text-xs text-(--color-text-secondary) leading-snug max-w-[200px] line-clamp-3"
                title={data.lastMessage}
              >
                {data.lastMessage}
              </div>
            ) : (
              <>
                {data.agentType && (
                  <div className="text-sm text-(--color-text-secondary)">{data.agentType}</div>
                )}
                {data.description && (
                  <div className="text-xs text-(--color-text-tertiary) mt-1 truncate max-w-[200px]">
                    {data.description}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* Source handle (output) - only for non-end nodes */}
      {!isEnd && (
        <Handle
          type="source"
          position={Position.Bottom}
          id="source"
          className="!bg-(--color-text-tertiary) !w-2 !h-2"
          isConnectable={isConnectable}
        />
      )}
    </div>
  )
}

export default memo(AgentNode)
