import React, { useCallback } from 'react';
import { Handle, Position } from '@xyflow/react';
import {
  Bot,
  CheckCircle,
  Flag,
  UserCircle,
  AlertTriangle,
  StopCircle,
} from 'lucide-react';
import type { AGLightNodeData } from './types';

interface Props {
  data: AGLightNodeData;
  isConnectable: boolean;
}

function statusIcon(status?: string | null) {
  switch (status) {
    case 'complete':
      return <CheckCircle className="text-accent" size={24} />;
    case 'error':
      return <AlertTriangle className="text-red-500" size={24} />;
    case 'stopped':
      return <StopCircle className="text-red-500" size={24} />;
    default:
      return null;
  }
}

export default function AGLightNode({ data, isConnectable }: Props) {
  const compact = data.compact === true;
  const handleClick = useCallback(() => {
    if (data.type !== 'end' && typeof data.jsonModuleAgent === 'string') {
      data.onSelectAgent?.(data.jsonModuleAgent);
    }
  }, [data]);

  const headerIcon = (() => {
    switch (data.type) {
      case 'user':
        return <UserCircle className="text-primary" size={20} />;
      case 'agent':
        return <Bot className="text-primary" size={20} />;
      case 'end':
        return <Flag className="text-primary" size={20} />;
    }
  })();

  const toneBorder: Record<string, string> = {
    law: 'rgba(96,165,250,0.55)',
    parking: 'rgba(94,234,212,0.55)',
    sunlight: 'rgba(251,191,36,0.55)',
    datum: 'rgba(250,204,21,0.55)',
    critic: 'rgba(167,139,250,0.55)',
    hub: 'rgba(45,212,191,0.55)',
  };

  const borderColor = data.type === 'end'
    ? (data.status === 'complete' ? 'rgba(34,197,94,0.75)' : data.status === 'error' ? 'rgba(239,68,68,0.75)' : 'rgba(148,163,184,0.45)')
    : toneBorder[data.tone || 'hub'] || 'rgba(148,163,184,0.35)';

  return (
    <div
      className={`relative shadow rounded-lg overflow-hidden ${data.isActive || data.selected ? 'ring-2 ring-accent/50' : ''}`}
      onClick={handleClick}
      style={{
        minWidth: compact ? 128 : (data.type === 'end' ? 170 : 176),
        width: compact ? 128 : undefined,
        border: `1px solid ${data.selected ? 'rgba(94,234,212,0.95)' : borderColor}`,
        background: data.type === 'end' ? 'rgba(2,6,23,0.88)' : 'rgba(2,6,23,0.84)',
        cursor: data.jsonModuleAgent ? 'pointer' : 'default',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: '#555' }} isConnectable={isConnectable} id="target" />

      <div className={`flex items-center gap-2 border-b border-border ${compact ? 'px-2 py-1.5' : 'px-3 py-2'}`} style={{ background: 'rgba(15,23,42,0.95)' }}>
        {headerIcon}
        <span className={`${compact ? 'text-xs' : 'text-sm'} font-medium truncate`} style={{ color: '#e2e8f0' }}>{data.label}</span>
      </div>

      <div className={compact ? 'px-2 py-1.5' : 'px-3 py-2'} style={{ background: 'rgba(2,6,23,0.52)' }}>
        {data.type === 'end' ? (
          <>
            <div className="flex items-center justify-center gap-2">
              {statusIcon(data.status)}
              <span className="text-sm font-medium" style={{ color: '#e2e8f0' }}>
                {data.status ? data.status.charAt(0).toUpperCase() + data.status.slice(1) : 'Idle'}
              </span>
            </div>
            {data.reason && (
              <div className="mt-1 text-xs text-secondary max-w-[200px] text-center">
                {data.reason.length > 100 ? `${data.reason.substring(0, 97)}...` : data.reason}
              </div>
            )}
          </>
        ) : (
          <>
            {data.agentType && (
              <div className="text-[10px] leading-tight truncate" style={{ color: '#60a5fa' }}>
                {data.agentType}
              </div>
            )}
            {typeof data.lastMessage === 'string' && data.lastMessage ? (
              <div
                className={`text-xs leading-snug ${compact ? 'mt-0.5 max-w-[112px] line-clamp-2' : 'mt-1 max-w-[200px] line-clamp-3'}`}
                style={{ color: '#cbd5e1' }}
                title={data.lastMessage}
              >
                {data.lastMessage}
              </div>
            ) : (
              <>
                {data.description && (
                  <div className={`text-xs mt-1 truncate ${compact ? 'max-w-[112px]' : 'max-w-[200px]'}`} style={{ color: '#94a3b8' }}>
                    {data.description}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {data.type !== 'end' && (
        <Handle type="source" position={Position.Bottom} id="source" style={{ background: '#555' }} isConnectable={isConnectable} />
      )}
    </div>
  );
}
