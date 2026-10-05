import { useState } from 'react';
import { X, Code } from 'lucide-react';
import { Card } from '@/features/workspace/ui/Card';
import { Button } from '@/features/workspace/ui/Button';
import { Badge } from '@/features/workspace/ui/Badge';
import { AgentHealthBadge } from './AgentHealthBadge';
import type { AgentSummary } from './api';

export function AgentDetailPanel({ agent, onClose }: { agent: AgentSummary; onClose: () => void }) {
  const [showJson, setShowJson] = useState(false);
  return <Card className="relative">
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-3"><h2 className="text-heading-small">{agent.label}</h2><AgentHealthBadge status={agent.connection_status} /></div>
      <button onClick={onClose} aria-label="Close detail panel" className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"><X className="w-4 h-4" /></button>
    </div>
    <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
      {Object.entries({ 'Agent ID': agent.agent_id, '구현 상태': agent.implementation_status, '확인 시각': agent.checked_at || '미기록', '근거': agent.evidence_ref || '미기록' }).map(([label, value]) => <div key={label}><span className="text-(--color-text-tertiary)">{label}</span><p className="font-medium break-all">{value}</p></div>)}
    </div>
    <div className="mt-4"><h3 className="text-sm font-medium text-(--color-text-secondary) mb-2">Skills</h3>
      <div className="flex flex-wrap gap-2">{agent.capabilities.map(skill => <Badge key={skill} variant="outline">{skill}</Badge>)}</div>
      {agent.capabilities.length === 0 && <p className="text-sm text-(--color-text-tertiary)">등록된 기능이 없습니다.</p>}
    </div>
    <div className="flex gap-2 mt-4"><Button size="sm" variant="ghost" onClick={() => setShowJson(!showJson)}><Code className="w-3.5 h-3.5 mr-1.5" />{showJson ? 'Hide JSON' : 'Show JSON'}</Button></div>
    {showJson && <pre className="mt-3 p-3 rounded-md bg-(--color-background-secondary) text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">{JSON.stringify(agent, null, 2)}</pre>}
  </Card>;
}
