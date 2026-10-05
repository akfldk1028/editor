'use client'

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Card } from '@/features/workspace/ui/Card';
import { Button } from '@/features/workspace/ui/Button';
import { listAgents } from './api';
import { AgentCard } from './AgentCard';
import { AgentDetailPanel } from './AgentDetailPanel';

export default function AgentsPage() {
  const query = useQuery({ queryKey: ['editor', 'agent-catalog'], queryFn: ({ signal }) => listAgents(signal), retry: false });
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const term = search.trim().toLowerCase();
  const agents = (query.isError ? [] : query.data || []).filter(a => [a.label, a.agent_id, ...a.capabilities].some(v => v.toLowerCase().includes(term)));
  const selectedAgent = agents.find(a => a.agent_id === selected);
  return <div className="space-y-6">
    <div className="flex items-center justify-between"><div><h1 className="text-display-medium">A2A Agents</h1><p className="text-body-medium text-(--color-text-secondary) mt-1">공유 에이전트 목록 · 연결 상태와 구현 상태</p></div>
      <Button variant="ghost" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={`w-4 h-4 mr-2 ${query.isFetching ? 'animate-spin' : ''}`} />목록 새로고침</Button>
    </div>
    <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search agents..." aria-label="Search agents"
      className="h-10 w-full max-w-sm px-4 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-(--color-text-primary) text-sm focus:outline-none focus:border-(--color-accent-primary) focus:ring-2 focus:ring-(--color-accent-primary)/20 placeholder:text-(--color-text-tertiary)" />
    {query.isError && <p role="alert" className="text-red-500">{query.error.message}</p>}
    {selectedAgent && <AgentDetailPanel key={selectedAgent.agent_id} agent={selectedAgent} onClose={() => setSelected(null)} />}
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {query.isPending ? [1, 2, 3].map(i => <Card key={i} className="animate-pulse"><div className="h-4 bg-(--color-background-secondary) rounded w-3/4" /><div className="h-3 bg-(--color-background-secondary) rounded w-1/2 mt-3" /></Card>) :
        agents.map(agent => <AgentCard key={agent.agent_id} agent={agent} isSelected={selected === agent.agent_id} onSelect={() => setSelected(selected === agent.agent_id ? null : agent.agent_id)} />)}
      {!query.isPending && !query.isError && agents.length === 0 && <Card className="col-span-full text-center py-12"><p className="text-body-large text-(--color-text-secondary)">{term ? 'No agents match your search.' : '공유 목록에 등록된 에이전트가 없습니다.'}</p></Card>}
    </div>
  </div>;
}
