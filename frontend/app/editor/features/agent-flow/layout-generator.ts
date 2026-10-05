import type { AGLightFlowSettings } from './AGLightFlowToolbar';
import { createNode, createEdge, type AGLightMessage, type AGLightReview, type AGLightRunStatus } from './types';

export type AGLightViewMode = 'pattern' | 'execution';

export function generateAGLightLayout({ messages = [], settings, selectedAgentId, onSelectAgent }: {
  reviews: AGLightReview[]; messages?: AGLightMessage[]; status: AGLightRunStatus;
  viewMode: AGLightViewMode; settings: AGLightFlowSettings; isFullscreen?: boolean;
  selectedAgentId?: string; onSelectAgent?: (id: string) => void;
}) {
  const ids = [...new Set(messages.flatMap(m => [m.from_agent, m.to_agent]))];
  const nodes = ids.map((id, index) => {
    const position = settings.direction === 'LR' ? { x: (index % 3) * 280, y: Math.floor(index / 3) * 180 } : { x: Math.floor(index / 3) * 280, y: (index % 3) * 180 };
    const last = messages.filter(m => m.from_agent === id || m.to_agent === id).at(-1);
    const node = createNode(id, 'agent', id, '기록에 등장한 참여자', position, { isActive: false, isProcessing: false, tone: id === 'orchestrator' ? 'hub' : 'law' });
    node.data = { ...node.data, jsonModuleAgent: id, selected: selectedAgentId === id, onSelectAgent, lastMessage: last?.message };
    return node;
  });
  const groups = new Map<string, AGLightMessage[]>();
  for (const message of messages) {
    const key = JSON.stringify([message.from_agent, message.to_agent]);
    groups.set(key, [...(groups.get(key) || []), message]);
  }
  const edges = [...groups.entries()].map(([key, rows]) => {
    const first = rows[0]!;
    const known = rows.every(m => m.metadata?.transport === 'a2a');
    return createEdge(key, first.from_agent, first.to_agent, { messages: rows,
      label: settings.showLabels ? `${known ? 'A2A' : '전송 미확인'} · ${rows.length}건` : '',
      routingType: first.to_agent === 'orchestrator' ? 'feedback' : 'primary', stroke: known ? '#38bdf8' : '#94a3b8', strokeWidth: 2 });
  });
  return { nodes, edges };
}
