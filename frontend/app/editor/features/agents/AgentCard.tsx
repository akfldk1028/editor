import { Card } from '@/features/workspace/ui/Card';
import { Badge } from '@/features/workspace/ui/Badge';
import { AgentHealthBadge } from './AgentHealthBadge';
import type { AgentSummary } from './api';

export function AgentCard({ agent, isSelected, onSelect }: { agent: AgentSummary; isSelected: boolean; onSelect: () => void }) {
  return <Card className={`hover:shadow-lg transition-shadow cursor-pointer ${isSelected ? 'ring-2 ring-(--color-accent-primary)' : ''}`}
    onClick={onSelect} role="button" tabIndex={0} aria-pressed={isSelected}
    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(); } }}>
    <div className="flex items-start justify-between">
      <div className="min-w-0 flex-1">
        <h3 className="text-heading-small truncate">{agent.label}</h3>
        <p className="text-body-small text-(--color-text-tertiary) mt-1 truncate">{agent.agent_id}</p>
      </div>
      <AgentHealthBadge status={agent.connection_status} />
    </div>
    {agent.capabilities.length > 0 && <div className="flex flex-wrap gap-1.5 mt-3">
      {agent.capabilities.map(skill => <Badge key={skill} variant="outline">{skill}</Badge>)}
    </div>}
    <p className="text-xs text-(--color-text-tertiary) mt-3">구현 상태: {agent.implementation_status}</p>
    <p className="text-xs font-mono text-(--color-text-tertiary) mt-3 truncate">확인 시각: {agent.checked_at || '미기록'}</p>
  </Card>;
}
